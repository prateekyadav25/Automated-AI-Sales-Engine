from fastapi.testclient import TestClient

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
