from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import httpx

from app.core.config import get_settings
from app.services.provider_ops import classify_http

CALL_STATUS_MAP = {
    "queued": "QUEUED",
    "initiated": "QUEUED",
    "ringing": "RINGING",
    "in-progress": "ANSWERED",
    "in_progress": "ANSWERED",
    "answered": "ANSWERED",
    "completed": "COMPLETED",
    "ended": "COMPLETED",
    "no-answer": "NO_ANSWER",
    "no_answer": "NO_ANSWER",
    "busy": "BUSY",
    "failed": "FAILED",
    "canceled": "CANCELLED",
    "cancelled": "CANCELLED",
}


def normalize_call_status(raw: str) -> str:
    return CALL_STATUS_MAP.get((raw or "").strip().lower(), "")


@dataclass(frozen=True)
class VoiceHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str


@dataclass(frozen=True)
class VoiceSession:
    ok: bool
    session_id: str
    provider: str
    is_mock: bool
    reason: str = ""
    status_code: int = 0
    failure_class: str = ""
    call_status: str = ""


@dataclass(frozen=True)
class TranscriptIngest:
    ok: bool
    session_id: str
    transcript: str
    provider: str
    is_mock: bool
    reason: str = ""


class VoiceProvider(Protocol):
    def health(self) -> VoiceHealth: ...

    def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession: ...

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest: ...


class MockVoiceProvider:
    def health(self) -> VoiceHealth:
        return VoiceHealth(
            provider="mock-voice",
            is_mock=True,
            connected=False,
            reason="VOICE_PROVIDER is mock. Dial is not placed. Paste a transcript instead.",
        )

    def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession:
        _ = (to_number, from_label)
        return VoiceSession(
            ok=False,
            session_id="",
            provider="mock-voice",
            is_mock=True,
            reason="Labeled mock. No outbound dial is placed without a live voice provider.",
            failure_class="CONFIGURATION",
        )

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest:
        text = transcript.strip()
        return TranscriptIngest(
            ok=bool(text),
            session_id=session_id or str(uuid4()),
            transcript=text,
            provider="mock-voice",
            is_mock=True,
            reason="" if text else "Transcript is empty.",
        )


class NotConfiguredVoiceProvider:
    def __init__(self, provider: str) -> None:
        self._provider = provider

    def health(self) -> VoiceHealth:
        return VoiceHealth(
            provider=self._provider,
            is_mock=False,
            connected=False,
            reason=f"VOICE_PROVIDER is {self._provider} but required credentials are missing.",
        )

    def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession:
        _ = (to_number, from_label)
        return VoiceSession(
            ok=False,
            session_id="",
            provider=self._provider,
            is_mock=False,
            reason=f"{self._provider} is not configured. No dial was placed.",
            failure_class="CONFIGURATION",
        )

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest:
        text = transcript.strip()
        return TranscriptIngest(
            ok=bool(text),
            session_id=session_id,
            transcript=text,
            provider=self._provider,
            is_mock=False,
            reason="" if text else "Transcript is empty.",
        )


class TwilioVoiceProvider:
    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        twiml_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._sid = account_sid
        self._token = auth_token
        self._from = from_number
        self._twiml = twiml_url
        self._client = client

    def health(self) -> VoiceHealth:
        return VoiceHealth(provider="twilio", is_mock=False, connected=True, reason="Twilio credentials are set.")

    def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession:
        _ = from_label
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Calls.json",
                auth=(self._sid, self._token),
                data={"To": to_number, "From": self._from, "Url": self._twiml},
            )
            if response.status_code >= 400:
                return VoiceSession(
                    ok=False,
                    session_id="",
                    provider="twilio",
                    is_mock=False,
                    reason=f"Twilio refused the call ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            session_id = str(data.get("sid") or "")
            return VoiceSession(
                ok=bool(session_id),
                session_id=session_id,
                provider="twilio",
                is_mock=False,
                call_status=normalize_call_status(str(data.get("status") or "queued")) or "QUEUED",
                reason="" if session_id else "Twilio returned no call sid.",
            )
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id="", provider="twilio", is_mock=False, reason="Twilio network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest:
        text = transcript.strip()
        return TranscriptIngest(
            ok=bool(text),
            session_id=session_id,
            transcript=text,
            provider="twilio",
            is_mock=False,
            reason="" if text else "Transcript is empty.",
        )


class VapiVoiceProvider:
    def __init__(
        self,
        *,
        api_key: str,
        assistant_id: str = "",
        phone_number_id: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        self._key = api_key
        self._assistant = assistant_id
        self._phone = phone_number_id
        self._client = client

    def health(self) -> VoiceHealth:
        return VoiceHealth(provider="vapi", is_mock=False, connected=True, reason="Vapi credentials are set.")

    def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        payload: dict[str, object] = {"customer": {"number": to_number}, "name": from_label or "AGRAYIAN gated dial"}
        if self._assistant:
            payload["assistantId"] = self._assistant
        if self._phone:
            payload["phoneNumberId"] = self._phone
        try:
            response = client.post(
                "https://api.vapi.ai/call",
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code >= 400:
                return VoiceSession(
                    ok=False,
                    session_id="",
                    provider="vapi",
                    is_mock=False,
                    reason=f"Vapi refused the call ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            session_id = str(data.get("id") or "")
            return VoiceSession(
                ok=bool(session_id),
                session_id=session_id,
                provider="vapi",
                is_mock=False,
                call_status=normalize_call_status(str(data.get("status") or "queued")) or "QUEUED",
                reason="" if session_id else "Vapi returned no call id.",
            )
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id="", provider="vapi", is_mock=False, reason="Vapi network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest:
        text = transcript.strip()
        return TranscriptIngest(
            ok=bool(text),
            session_id=session_id,
            transcript=text,
            provider="vapi",
            is_mock=False,
            reason="" if text else "Transcript is empty.",
        )


def get_voice_provider() -> VoiceProvider:
    settings = get_settings()
    mode = (settings.voice_provider or "mock").strip().lower()
    if mode == "twilio":
        if settings.twilio_configured:
            return TwilioVoiceProvider(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token,
                from_number=settings.twilio_from_number,
                twiml_url=settings.twilio_twiml_url,
            )
        return NotConfiguredVoiceProvider("twilio")
    if mode == "vapi":
        if settings.vapi_configured:
            return VapiVoiceProvider(
                api_key=settings.vapi_api_key,
                assistant_id=settings.vapi_assistant_id,
                phone_number_id=settings.vapi_phone_number_id,
            )
        return NotConfiguredVoiceProvider("vapi")
    return MockVoiceProvider()
