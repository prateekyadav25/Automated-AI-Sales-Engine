from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx
from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.provider_ops import classify_http
from app.services.provider_resolve import resolve_channel


@dataclass(frozen=True)
class MeetingCaptureHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str


@dataclass(frozen=True)
class MeetingCaptureResult:
    ok: bool
    provider: str
    is_mock: bool
    bot_id: str = ""
    status: str = ""
    transcript: str = ""
    recording_ref: str = ""
    reason: str = ""
    failure_class: str = ""


class MeetingCaptureProvider(Protocol):
    def health(self) -> MeetingCaptureHealth: ...

    def schedule_bot(self, *, meeting_url: str, title: str = "") -> MeetingCaptureResult: ...

    def fetch(self, *, bot_id: str) -> MeetingCaptureResult: ...


class MockMeetingCaptureProvider:
    def health(self) -> MeetingCaptureHealth:
        return MeetingCaptureHealth(provider="mock-capture", is_mock=True, connected=False, reason="Meeting capture is mock. Use manual paste.")

    def schedule_bot(self, *, meeting_url: str, title: str = "") -> MeetingCaptureResult:
        _ = (meeting_url, title)
        return MeetingCaptureResult(ok=False, provider="mock-capture", is_mock=True, reason="Labeled mock does not join meetings.", failure_class="CONFIGURATION")

    def fetch(self, *, bot_id: str) -> MeetingCaptureResult:
        return MeetingCaptureResult(ok=False, provider="mock-capture", is_mock=True, bot_id=bot_id, reason="Mock has no transcript.")


class NotConfiguredMeetingCaptureProvider:
    def health(self) -> MeetingCaptureHealth:
        return MeetingCaptureHealth(provider="recall", is_mock=False, connected=False, reason="Meeting capture is live but credentials are missing.")

    def schedule_bot(self, *, meeting_url: str, title: str = "") -> MeetingCaptureResult:
        _ = (meeting_url, title)
        return MeetingCaptureResult(ok=False, provider="recall", is_mock=False, reason="Meeting capture is not configured.", failure_class="CONFIGURATION")

    def fetch(self, *, bot_id: str) -> MeetingCaptureResult:
        return MeetingCaptureResult(ok=False, provider="recall", is_mock=False, bot_id=bot_id, reason="Meeting capture is not configured.")


class ManualMeetingCaptureProvider:
    def health(self) -> MeetingCaptureHealth:
        return MeetingCaptureHealth(provider="manual", is_mock=False, connected=True, reason="Manual paste is always available.")

    def schedule_bot(self, *, meeting_url: str, title: str = "") -> MeetingCaptureResult:
        _ = (meeting_url, title)
        return MeetingCaptureResult(ok=False, provider="manual", is_mock=False, reason="Manual capture does not join a meeting. Paste a transcript.", failure_class="CONFIGURATION")

    def fetch(self, *, bot_id: str) -> MeetingCaptureResult:
        return MeetingCaptureResult(ok=True, provider="manual", is_mock=False, bot_id=bot_id, status="manual")


class UploadMeetingCaptureProvider:
    def health(self) -> MeetingCaptureHealth:
        settings = get_settings()
        live = settings.openai_configured
        return MeetingCaptureHealth(
            provider="upload-stt",
            is_mock=not live,
            connected=live,
            reason="OpenAI Whisper is used for uploaded audio." if live else "Upload STT is not configured. Paste a transcript.",
        )

    def schedule_bot(self, *, meeting_url: str, title: str = "") -> MeetingCaptureResult:
        _ = (meeting_url, title)
        return MeetingCaptureResult(ok=False, provider="upload-stt", is_mock=False, reason="Upload capture expects a file, not a meeting URL.", failure_class="CONFIGURATION")

    def fetch(self, *, bot_id: str) -> MeetingCaptureResult:
        return MeetingCaptureResult(ok=False, provider="upload-stt", is_mock=False, bot_id=bot_id, reason="No stored upload for this id.")

    def transcribe(self, *, filename: str, data: bytes) -> MeetingCaptureResult:
        _ = filename
        settings = get_settings()
        if not settings.openai_configured:
            return MeetingCaptureResult(ok=False, provider="upload-stt", is_mock=False, reason="STT is not configured.", failure_class="CONFIGURATION")
        client = OpenAI(api_key=settings.openai_api_key)
        try:
            audio = client.audio.transcriptions.create(model="whisper-1", file=("meeting.webm", data))
            text = getattr(audio, "text", "") or ""
            return MeetingCaptureResult(ok=bool(text.strip()), provider="upload-stt", is_mock=False, transcript=text.strip(), status="completed", reason="" if text.strip() else "Whisper returned an empty transcript.")
        except Exception as exc:  # noqa: BLE001
            return MeetingCaptureResult(ok=False, provider="upload-stt", is_mock=False, reason=str(exc)[:200], failure_class="TRANSIENT")


class RecallMeetingCaptureProvider:
    def __init__(self, *, api_key: str, client: httpx.Client | None = None) -> None:
        self._key = api_key
        self._client = client

    def health(self) -> MeetingCaptureHealth:
        return MeetingCaptureHealth(provider="recall", is_mock=False, connected=True, reason="Recall.ai credentials are set.")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._key}", "Content-Type": "application/json"}

    def schedule_bot(self, *, meeting_url: str, title: str = "") -> MeetingCaptureResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                "https://us-west-2.recall.ai/api/v1/bot/",
                headers=self._headers(),
                json={"meeting_url": meeting_url, "bot_name": title or "AGRAYIAN notetaker"},
            )
            if response.status_code >= 400:
                return MeetingCaptureResult(
                    ok=False,
                    provider="recall",
                    is_mock=False,
                    reason=f"Recall refused bot create ({response.status_code}).",
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            bot_id = str(data.get("id") or "")
            return MeetingCaptureResult(ok=bool(bot_id), provider="recall", is_mock=False, bot_id=bot_id, status=str(data.get("status_changes") or "scheduled"))
        except httpx.HTTPError:
            return MeetingCaptureResult(ok=False, provider="recall", is_mock=False, reason="Recall network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def fetch(self, *, bot_id: str) -> MeetingCaptureResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.get(f"https://us-west-2.recall.ai/api/v1/bot/{bot_id}/", headers=self._headers())
            if response.status_code >= 400:
                return MeetingCaptureResult(ok=False, provider="recall", is_mock=False, bot_id=bot_id, reason="Recall bot read refused.")
            data = response.json() if response.content else {}
            video = ""
            recordings = data.get("recordings") if isinstance(data, dict) else None
            if isinstance(recordings, list) and recordings and isinstance(recordings[0], dict):
                video = str(recordings[0].get("media_shortcuts", {}).get("video_mixed", {}).get("data", {}).get("download_url") or "")
            transcript = ""
            transcript_url = ""
            if isinstance(data, dict):
                transcript_url = str(((data.get("transcript") or {}) if isinstance(data.get("transcript"), dict) else {}).get("download_url") or "")
            if transcript_url:
                downloaded = client.get(transcript_url, headers=self._headers())
                if downloaded.status_code < 400:
                    payload = downloaded.json() if downloaded.content else []
                    if isinstance(payload, list):
                        parts = []
                        for item in payload:
                            if isinstance(item, dict):
                                words = item.get("words") or []
                                if isinstance(words, list):
                                    parts.append(" ".join(str(word.get("text") or "") for word in words if isinstance(word, dict)))
                        transcript = " ".join(part for part in parts if part)
            return MeetingCaptureResult(
                ok=True,
                provider="recall",
                is_mock=False,
                bot_id=bot_id,
                status=str(data.get("status") or "unknown"),
                transcript=transcript,
                recording_ref=video,
            )
        except httpx.HTTPError:
            return MeetingCaptureResult(ok=False, provider="recall", is_mock=False, bot_id=bot_id, reason="Recall network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()


def get_meeting_capture_provider(db: Session | None = None, tenant_id: UUID | None = None, kind: str = "") -> MeetingCaptureProvider:
    settings = get_settings()
    chosen = (kind or settings.meeting_capture_provider or "mock").strip().lower()
    if chosen == "manual":
        return ManualMeetingCaptureProvider()
    if chosen == "upload":
        return UploadMeetingCaptureProvider()
    if db is not None and tenant_id is not None:
        resolved = resolve_channel(db, tenant_id, "recall")
        if resolved.mode == "LIVE" and resolved.secrets.get("access_token"):
            return RecallMeetingCaptureProvider(api_key=resolved.secrets["access_token"])
        if resolved.mode == "MOCK" or chosen == "mock":
            return MockMeetingCaptureProvider()
        return NotConfiguredMeetingCaptureProvider()
    if chosen in {"recall", "live"} and settings.recall_configured:
        return RecallMeetingCaptureProvider(api_key=settings.recall_api_key)
    if chosen in {"recall", "live"}:
        return NotConfiguredMeetingCaptureProvider()
    return MockMeetingCaptureProvider()
