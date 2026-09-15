from typing import Protocol
from uuid import uuid4

import httpx

from app.providers.voice import TranscriptIngest, VoiceHealth, VoiceSession
from app.services.provider_ops import classify_http


class VoiceConversationProvider(Protocol):
    def health(self) -> VoiceHealth: ...

    def attach(self, *, session_id: str, to_number: str, script: str = "", metadata: dict | None = None) -> VoiceSession: ...

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest: ...


class MockConversationProvider:
    def health(self) -> VoiceHealth:
        return VoiceHealth(provider="mock-conversation", is_mock=True, connected=False, reason="Conversation provider is mock. Paste a transcript instead.")

    def attach(self, *, session_id: str, to_number: str, script: str = "", metadata: dict | None = None) -> VoiceSession:
        _ = (to_number, script, metadata)
        return VoiceSession(ok=False, session_id=session_id, provider="mock-conversation", is_mock=True, reason="Labeled mock conversation. No AI speaker is attached.", failure_class="CONFIGURATION")

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest:
        text = transcript.strip()
        return TranscriptIngest(ok=bool(text), session_id=session_id or str(uuid4()), transcript=text, provider="mock-conversation", is_mock=True, reason="" if text else "Transcript is empty.")


class NotConfiguredConversationProvider:
    def __init__(self, provider: str) -> None:
        self._provider = provider

    def health(self) -> VoiceHealth:
        return VoiceHealth(provider=self._provider, is_mock=False, connected=False, reason=f"{self._provider} conversation credentials are missing.")

    def attach(self, *, session_id: str, to_number: str, script: str = "", metadata: dict | None = None) -> VoiceSession:
        _ = (to_number, script, metadata)
        return VoiceSession(ok=False, session_id=session_id, provider=self._provider, is_mock=False, reason=f"{self._provider} is not configured.", failure_class="CONFIGURATION")

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest:
        text = transcript.strip()
        return TranscriptIngest(ok=bool(text), session_id=session_id, transcript=text, provider=self._provider, is_mock=False, reason="" if text else "Transcript is empty.")


class VapiConversationProvider:
    def __init__(self, *, api_key: str, assistant_id: str = "", phone_number_id: str = "", client: httpx.Client | None = None) -> None:
        self._key = api_key
        self._assistant = assistant_id
        self._phone = phone_number_id
        self._client = client

    def health(self) -> VoiceHealth:
        return VoiceHealth(provider="vapi", is_mock=False, connected=True, reason="Vapi credentials are set.")

    def attach(self, *, session_id: str, to_number: str, script: str = "", metadata: dict | None = None) -> VoiceSession:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        payload: dict[str, object] = {"customer": {"number": to_number}, "name": "AGRAYIAN gated dial"}
        if self._assistant:
            payload["assistantId"] = self._assistant
        if script:
            payload["assistant"] = {
                "firstMessage": script[:500],
                "model": {"messages": [{"role": "system", "content": script[:8000]}]},
            }
        if self._phone:
            payload["phoneNumberId"] = self._phone
        if session_id:
            payload["metadata"] = {**(metadata or {}), "telephony_session_id": session_id}
        try:
            response = client.post(
                "https://api.vapi.ai/call",
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code >= 400:
                return VoiceSession(
                    ok=False,
                    session_id=session_id,
                    provider="vapi",
                    is_mock=False,
                    reason=f"Vapi refused the conversation ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            attached = str(data.get("id") or session_id)
            return VoiceSession(ok=True, session_id=attached, provider="vapi", is_mock=False, call_status="QUEUED")
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id=session_id, provider="vapi", is_mock=False, reason="Vapi network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest:
        text = transcript.strip()
        return TranscriptIngest(ok=bool(text), session_id=session_id, transcript=text, provider="vapi", is_mock=False, reason="" if text else "Transcript is empty.")


class HumanHandoffConversation:
    def __init__(self, *, dest_number: str = "") -> None:
        self._dest = dest_number

    def health(self) -> VoiceHealth:
        return VoiceHealth(provider="human-handoff", is_mock=False, connected=True, reason="Human handoff is selected. A rep is connected instead of hosted AI.")

    def attach(self, *, session_id: str, to_number: str, script: str = "", metadata: dict | None = None) -> VoiceSession:
        _ = (to_number, script)
        dest = self._dest or str((metadata or {}).get("handoff_number") or "")
        return VoiceSession(
            ok=True,
            session_id=session_id,
            provider="human-handoff",
            is_mock=False,
            call_status="QUEUED",
            reason=f"Connect a human at {dest}" if dest else "Connect a human agent on this bridge.",
        )

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest:
        text = transcript.strip()
        return TranscriptIngest(ok=bool(text), session_id=session_id, transcript=text, provider="human-handoff", is_mock=False, reason="" if text else "Transcript is empty.")


class SelfHostedConversation(NotConfiguredConversationProvider):
    def __init__(self) -> None:
        super().__init__("self-hosted")

    def health(self) -> VoiceHealth:
        return VoiceHealth(provider="self-hosted", is_mock=False, connected=False, reason="Self-hosted STT+LLM+TTS is not configured.")
