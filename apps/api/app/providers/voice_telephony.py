from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.providers.voice import VoiceHealth, VoiceSession, normalize_call_status
from app.services.provider_ops import classify_http


class VoiceTelephonyProvider(Protocol):
    def health(self) -> VoiceHealth: ...

    def dial(
        self,
        *,
        to_number: str,
        from_label: str = "",
        status_callback: str = "",
        record: bool = True,
        announcement: str = "",
    ) -> VoiceSession: ...

    def hangup(self, *, session_id: str) -> VoiceSession: ...

    def get_status(self, *, session_id: str) -> VoiceSession: ...


class MockTelephonyProvider:
    def health(self) -> VoiceHealth:
        return VoiceHealth(
            provider="mock-telephony",
            is_mock=True,
            connected=False,
            reason="Telephony is mock. No outbound dial is placed.",
        )

    def dial(self, *, to_number: str, from_label: str = "", status_callback: str = "", record: bool = True, announcement: str = "") -> VoiceSession:
        _ = (to_number, from_label, status_callback, record, announcement)
        return VoiceSession(
            ok=False,
            session_id="",
            provider="mock-telephony",
            is_mock=True,
            reason="Labeled mock. No outbound dial is placed without a live telephony provider.",
            failure_class="CONFIGURATION",
        )

    def hangup(self, *, session_id: str) -> VoiceSession:
        return VoiceSession(ok=False, session_id=session_id, provider="mock-telephony", is_mock=True, reason="Mock cannot hang up a live call.", failure_class="CONFIGURATION")

    def get_status(self, *, session_id: str) -> VoiceSession:
        return VoiceSession(ok=False, session_id=session_id, provider="mock-telephony", is_mock=True, reason="Mock has no call status.")


class NotConfiguredTelephonyProvider:
    def __init__(self, provider: str) -> None:
        self._provider = provider

    def health(self) -> VoiceHealth:
        return VoiceHealth(
            provider=self._provider,
            is_mock=False,
            connected=False,
            reason=f"{self._provider} telephony is selected but required credentials are missing.",
        )

    def dial(self, *, to_number: str, from_label: str = "", status_callback: str = "", record: bool = True, announcement: str = "") -> VoiceSession:
        _ = (to_number, from_label, status_callback, record, announcement)
        return VoiceSession(
            ok=False,
            session_id="",
            provider=self._provider,
            is_mock=False,
            reason=f"{self._provider} is not configured. No dial was placed.",
            failure_class="CONFIGURATION",
        )

    def hangup(self, *, session_id: str) -> VoiceSession:
        return VoiceSession(ok=False, session_id=session_id, provider=self._provider, is_mock=False, reason="Not configured.", failure_class="CONFIGURATION")

    def get_status(self, *, session_id: str) -> VoiceSession:
        return VoiceSession(ok=False, session_id=session_id, provider=self._provider, is_mock=False, reason="Not configured.")


class TwilioTelephonyProvider:
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

    def dial(self, *, to_number: str, from_label: str = "", status_callback: str = "", record: bool = True, announcement: str = "") -> VoiceSession:
        _ = (from_label, announcement)
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        data = {"To": to_number, "From": self._from, "Url": self._twiml}
        if status_callback:
            data["StatusCallback"] = status_callback
            data["StatusCallbackEvent"] = "initiated ringing answered completed"
        if record:
            data["Record"] = "true"
        try:
            response = client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Calls.json",
                auth=(self._sid, self._token),
                data=data,
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
            payload = response.json() if response.content else {}
            session_id = str(payload.get("sid") or "")
            return VoiceSession(
                ok=bool(session_id),
                session_id=session_id,
                provider="twilio",
                is_mock=False,
                call_status=normalize_call_status(str(payload.get("status") or "queued")) or "QUEUED",
                reason="" if session_id else "Twilio returned no call sid.",
            )
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id="", provider="twilio", is_mock=False, reason="Twilio network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def hangup(self, *, session_id: str) -> VoiceSession:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Calls/{session_id}.json",
                auth=(self._sid, self._token),
                data={"Status": "completed"},
            )
            if response.status_code >= 400:
                return VoiceSession(ok=False, session_id=session_id, provider="twilio", is_mock=False, reason=f"Twilio hangup refused ({response.status_code}).", failure_class=classify_http(response.status_code))
            return VoiceSession(ok=True, session_id=session_id, provider="twilio", is_mock=False, call_status="CANCELLED")
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id=session_id, provider="twilio", is_mock=False, reason="Twilio network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def get_status(self, *, session_id: str) -> VoiceSession:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Calls/{session_id}.json",
                auth=(self._sid, self._token),
            )
            if response.status_code >= 400:
                return VoiceSession(ok=False, session_id=session_id, provider="twilio", is_mock=False, reason="Twilio status refused.")
            payload = response.json() if response.content else {}
            return VoiceSession(
                ok=True,
                session_id=session_id,
                provider="twilio",
                is_mock=False,
                call_status=normalize_call_status(str(payload.get("status") or "")),
            )
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id=session_id, provider="twilio", is_mock=False, reason="Twilio network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()


@dataclass(frozen=True)
class ExotelConnect:
    sid: str
    api_key: str
    api_token: str
    caller_id: str
    subdomain: str = "api.exotel.com"


class ExotelTelephonyProvider:
    """India-primary carrier. Callbacks are routing-token authenticated; Exotel does not HMAC-sign them."""

    def __init__(self, *, sid: str, api_key: str, api_token: str, caller_id: str, subdomain: str = "api.exotel.com", client: httpx.Client | None = None) -> None:
        self._sid = sid
        self._key = api_key
        self._token = api_token
        self._from = caller_id
        self._host = subdomain or "api.exotel.com"
        self._client = client

    def health(self) -> VoiceHealth:
        return VoiceHealth(provider="exotel", is_mock=False, connected=True, reason="Exotel credentials are set. Callbacks use a routing token, not an HMAC signature.")

    def dial(self, *, to_number: str, from_label: str = "", status_callback: str = "", record: bool = True, announcement: str = "") -> VoiceSession:
        _ = (from_label, announcement)
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        url = f"https://{self._host}/v1/Accounts/{self._sid}/Calls/connect.json"
        data = {"From": self._from, "To": to_number, "CallerId": self._from}
        if status_callback:
            data["StatusCallback"] = status_callback
        if record:
            data["Record"] = "true"
        try:
            response = client.post(url, auth=(self._key, self._token), data=data)
            if response.status_code >= 400:
                return VoiceSession(
                    ok=False,
                    session_id="",
                    provider="exotel",
                    is_mock=False,
                    reason=f"Exotel refused the call ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            payload = response.json() if response.content else {}
            call = payload.get("Call") if isinstance(payload, dict) else {}
            if not isinstance(call, dict):
                call = payload if isinstance(payload, dict) else {}
            session_id = str(call.get("Sid") or call.get("sid") or "")
            return VoiceSession(
                ok=bool(session_id),
                session_id=session_id,
                provider="exotel",
                is_mock=False,
                call_status=normalize_call_status(str(call.get("Status") or call.get("status") or "queued")) or "QUEUED",
                reason="" if session_id else "Exotel returned no call sid.",
            )
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id="", provider="exotel", is_mock=False, reason="Exotel network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def hangup(self, *, session_id: str) -> VoiceSession:
        return VoiceSession(ok=False, session_id=session_id, provider="exotel", is_mock=False, reason="Exotel hangup is not exposed on this adapter.", failure_class="PERMANENT")

    def get_status(self, *, session_id: str) -> VoiceSession:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.get(
                f"https://{self._host}/v1/Accounts/{self._sid}/Calls/{session_id}.json",
                auth=(self._key, self._token),
            )
            if response.status_code >= 400:
                return VoiceSession(ok=False, session_id=session_id, provider="exotel", is_mock=False, reason="Exotel status refused.")
            payload = response.json() if response.content else {}
            call = payload.get("Call") if isinstance(payload, dict) else {}
            if not isinstance(call, dict):
                call = payload if isinstance(payload, dict) else {}
            return VoiceSession(
                ok=True,
                session_id=session_id,
                provider="exotel",
                is_mock=False,
                call_status=normalize_call_status(str(call.get("Status") or call.get("status") or "")),
            )
        except httpx.HTTPError:
            return VoiceSession(ok=False, session_id=session_id, provider="exotel", is_mock=False, reason="Exotel network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()


def telephony_status_callback(provider: str, routing_token: str) -> str:
    settings = get_settings()
    base = (settings.public_api_base_url or "http://localhost:8000").rstrip("/")
    return urljoin(f"{base}/", f"api/v1/webhooks/{provider}/{routing_token}")
