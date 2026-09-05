from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import httpx

from app.core.config import get_settings


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
            reason="No Twilio/Vapi keys. Dial is not placed. Paste a transcript instead.",
        )

    def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession:
        _ = (to_number, from_label)
        return VoiceSession(
            ok=False,
            session_id="",
            provider="mock-voice",
            is_mock=True,
            reason="Labeled mock. No outbound dial is placed without a live voice provider.",
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
                return VoiceSession(ok=False, session_id="", provider="twilio", is_mock=False, reason=f"Twilio refused the call ({response.status_code}).")
            data = response.json() if response.content else {}
            return VoiceSession(ok=True, session_id=str(data.get("sid") or ""), provider="twilio", is_mock=False)
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id="", provider="twilio", is_mock=False, reason="Twilio network error.")
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
    def __init__(self, *, api_key: str, client: httpx.Client | None = None) -> None:
        self._key = api_key
        self._client = client

    def health(self) -> VoiceHealth:
        return VoiceHealth(provider="vapi", is_mock=False, connected=True, reason="Vapi credentials are set.")

    def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                "https://api.vapi.ai/call",
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"customer": {"number": to_number}, "name": from_label or "AGRAYIAN gated dial"},
            )
            if response.status_code >= 400:
                return VoiceSession(ok=False, session_id="", provider="vapi", is_mock=False, reason=f"Vapi refused the call ({response.status_code}).")
            data = response.json() if response.content else {}
            return VoiceSession(ok=True, session_id=str(data.get("id") or ""), provider="vapi", is_mock=False)
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id="", provider="vapi", is_mock=False, reason="Vapi network error.")
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
    if settings.twilio_configured:
        return TwilioVoiceProvider(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_from_number,
            twiml_url=settings.twilio_twiml_url,
        )
    if settings.vapi_configured:
        return VapiVoiceProvider(api_key=settings.vapi_api_key)
    return MockVoiceProvider()
