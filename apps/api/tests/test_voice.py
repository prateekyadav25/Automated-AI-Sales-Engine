import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.providers.voice import VoiceHealth, VoiceSession
from tests.conftest import login


def test_dial_requires_consent_and_phone(client: TestClient) -> None:
    headers = login(client)
    contact = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"first_name": "Voice", "last_name": "Gate", "email": "voice.gate@example.com", "phone": "+15555550100"},
    )
    contact_id = contact.json()["data"]["id"]
    refused = client.post(
        "/api/v1/lifecycle/conversations/dial",
        headers=headers,
        json={"contact_id": contact_id, "consent": False},
    )
    assert refused.status_code == 409
    queued = client.post(
        "/api/v1/lifecycle/conversations/dial",
        headers=headers,
        json={"contact_id": contact_id, "consent": True},
    )
    assert queued.status_code == 200, queued.text
    approval_id = queued.json()["data"]["approval_id"]
    decided = client.post(
        f"/api/v1/ai/approvals/{approval_id}/decide",
        headers=headers,
        json={"decision": "approve", "note": "Try dial"},
    )
    assert decided.status_code == 200
    assert "not placed" in decided.json()["data"]["decision_note"].lower() or "mock" in decided.json()["data"]["decision_note"].lower()


class LiveVoiceStub:
    def __init__(self, session_id: str = "CA123") -> None:
        self.dials = 0
        self.session_id = session_id

    def health(self) -> VoiceHealth:
        return VoiceHealth(provider="twilio", is_mock=False, connected=True, reason="stub")

    def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession:
        self.dials += 1
        return VoiceSession(ok=True, session_id=self.session_id, provider="twilio", is_mock=False, call_status="QUEUED")

    def ingest_transcript(self, *, session_id: str, transcript: str):
        from app.providers.voice import TranscriptIngest

        return TranscriptIngest(ok=bool(transcript.strip()), session_id=session_id, transcript=transcript.strip(), provider="twilio", is_mock=False)


def test_successful_dial_and_duplicate_approval(client: TestClient, monkeypatch) -> None:
    stub = LiveVoiceStub()
    monkeypatch.setattr("app.services.voice.get_voice_provider", lambda *args, **kwargs: stub)
    headers = login(client)
    contact = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={
            "first_name": "Live",
            "last_name": "Voice",
            "email": "live.voice@example.com",
            "phone": "+15555550111",
            "preferred_channel": "VOICE",
            "consent_voice": True,
        },
    )
    queued = client.post(
        "/api/v1/lifecycle/conversations/dial",
        headers=headers,
        json={"contact_id": contact.json()["data"]["id"], "consent": True},
    )
    approval_id = queued.json()["data"]["approval_id"]
    first = client.post(f"/api/v1/ai/approvals/{approval_id}/decide", headers=headers, json={"decision": "approve", "note": "dial"})
    assert first.status_code == 200
    assert "CA123" in first.json()["data"]["decision_note"]
    second = client.post(f"/api/v1/ai/approvals/{approval_id}/decide", headers=headers, json={"decision": "approve", "note": "again"})
    assert second.status_code == 200
    assert stub.dials == 1


def test_callback_dedupe_and_do_not_call(client: TestClient, monkeypatch) -> None:
    stub = LiveVoiceStub(session_id="CA-DNC-1")
    monkeypatch.setattr("app.services.voice.get_voice_provider", lambda *args, **kwargs: stub)
    headers = login(client)
    contact = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={
            "first_name": "Stop",
            "last_name": "Call",
            "email": "stop.call@example.com",
            "phone": "+15555550112",
            "preferred_channel": "VOICE",
            "consent_voice": True,
        },
    )
    queued = client.post(
        "/api/v1/lifecycle/conversations/dial",
        headers=headers,
        json={"contact_id": contact.json()["data"]["id"], "consent": True},
    )
    client.post(f"/api/v1/ai/approvals/{queued.json()['data']['approval_id']}/decide", headers=headers, json={"decision": "approve", "note": "dial"})
    body = json.dumps(
        {
            "external_id": "CA-DNC-1",
            "CallSid": "CA-DNC-1",
            "CallStatus": "completed",
            "transcript": "Please do not call me again.",
        }
    ).encode()
    secret = get_settings().integrations_webhook_secret or get_settings().secret_key
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    from app.services.webhook_routes import demo_routing_token

    token = demo_routing_token("agrayian", "twilio")
    first = client.post(
        f"/api/v1/webhooks/twilio/{token}",
        headers={"X-Webhook-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    second = client.post(
        f"/api/v1/webhooks/twilio/{token}",
        headers={"X-Webhook-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["status"] in {"already", "processed", "queued"}
    refreshed = client.get("/api/v1/contacts", headers=headers, params={"q": "Stop"}).json()["data"]
    assert any(row["opt_out"] for row in refreshed if row["email"] == "stop.call@example.com")


def test_call_failure_records_failed_status(client: TestClient, monkeypatch) -> None:
    class FailVoice(LiveVoiceStub):
        def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession:
            return VoiceSession(ok=False, session_id="", provider="twilio", is_mock=False, reason="Twilio refused", failure_class="TRANSIENT")

    monkeypatch.setattr("app.services.voice.get_voice_provider", lambda *args, **kwargs: FailVoice())
    headers = login(client)
    contact = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"first_name": "Fail", "last_name": "Dial", "email": "fail.dial@example.com", "phone": "+15555550113", "consent_voice": True},
    )
    queued = client.post(
        "/api/v1/lifecycle/conversations/dial",
        headers=headers,
        json={"contact_id": contact.json()["data"]["id"], "consent": True},
    )
    decided = client.post(
        f"/api/v1/ai/approvals/{queued.json()['data']['approval_id']}/decide",
        headers=headers,
        json={"decision": "approve", "note": "dial"},
    )
    assert "refused" in decided.json()["data"]["decision_note"].lower() or "not placed" in decided.json()["data"]["decision_note"].lower()


def test_extract_meeting_notes_from_transcript(client: TestClient) -> None:
    headers = login(client)
    extracted = client.post(
        "/api/v1/lifecycle/meetings/extract",
        headers=headers,
        json={
            "title": "Discovery recap",
            "transcript": "We agreed to review security controls next Tuesday. No budget number was stated.",
        },
    )
    assert extracted.status_code == 200, extracted.text
    body = extracted.json()["data"]
    assert "security" in body["summary"].lower() or "transcript" in body["summary"].lower() or body["summary"]
    empty = client.post(
        "/api/v1/lifecycle/meetings/extract",
        headers=headers,
        json={"title": "Empty", "transcript": "   "},
    )
    assert empty.status_code == 422
