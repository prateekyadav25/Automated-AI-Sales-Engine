import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings


@dataclass(frozen=True)
class EmailHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    state: str = "MOCK"
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error_summary: str = ""


@dataclass(frozen=True)
class EmailSendResult:
    ok: bool
    provider: str
    is_mock: bool
    provider_message_id: str = ""
    thread_id: str = ""
    status: str = "sent"
    reason: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class InboundEmail:
    provider_message_id: str
    thread_id: str
    from_addr: str
    to_addrs: list[str]
    subject: str
    body_text: str
    received_at: datetime
    history_id: str = ""


class EmailProvider(Protocol):
    def health(self) -> EmailHealth: ...

    def send(self, *, to: str, subject: str, body: str, thread_id: str = "") -> EmailSendResult: ...

    def reply(self, *, to: str, subject: str, body: str, thread_id: str) -> EmailSendResult: ...

    def thread_lookup(self, *, thread_id: str) -> dict: ...

    def message_status(self, *, provider_message_id: str) -> dict: ...

    def list_since(self, *, history_id: str = "") -> list[InboundEmail]: ...

    def get_message(self, *, provider_message_id: str) -> InboundEmail | None: ...


class MockEmailProvider:
    inbox: list[InboundEmail] = []

    def health(self) -> EmailHealth:
        return EmailHealth(
            provider="mock-email",
            is_mock=True,
            connected=True,
            reason="Labeled mock. Approved sends persist a provider id. Live Gmail is not configured.",
            state="MOCK",
        )

    def send(self, *, to: str, subject: str, body: str, thread_id: str = "") -> EmailSendResult:
        message_id = f"mock-email-{uuid4()}"
        return EmailSendResult(
            ok=True,
            provider="mock-email",
            is_mock=True,
            provider_message_id=message_id,
            thread_id=thread_id or f"thread-{uuid4()}",
            status="sent",
            reason="Mock send persisted. No live mailbox was contacted.",
        )

    def reply(self, *, to: str, subject: str, body: str, thread_id: str) -> EmailSendResult:
        return self.send(to=to, subject=subject, body=body, thread_id=thread_id)

    def thread_lookup(self, *, thread_id: str) -> dict:
        return {"thread_id": thread_id, "messages": [], "provider": "mock-email", "is_mock": True}

    def message_status(self, *, provider_message_id: str) -> dict:
        return {"provider_message_id": provider_message_id, "status": "sent", "provider": "mock-email", "is_mock": True}

    def list_since(self, *, history_id: str = "") -> list[InboundEmail]:
        return list(self.inbox)

    def get_message(self, *, provider_message_id: str) -> InboundEmail | None:
        for item in self.inbox:
            if item.provider_message_id == provider_message_id:
                return item
        return None


class DisconnectedGmailProvider:
    def health(self) -> EmailHealth:
        return EmailHealth(
            provider="gmail",
            is_mock=False,
            connected=False,
            reason="EMAIL_PROVIDER is gmail but no connected Google account with mail scopes exists.",
            state="NOT_CONFIGURED",
        )

    def send(self, *, to: str, subject: str, body: str, thread_id: str = "") -> EmailSendResult:
        return EmailSendResult(
            ok=False,
            provider="gmail",
            is_mock=False,
            status="FAILED",
            reason="BLOCKED BY CONFIGURATION",
            retryable=False,
        )

    def reply(self, *, to: str, subject: str, body: str, thread_id: str) -> EmailSendResult:
        return self.send(to=to, subject=subject, body=body, thread_id=thread_id)

    def thread_lookup(self, *, thread_id: str) -> dict:
        return {"thread_id": thread_id, "messages": [], "provider": "gmail", "is_mock": False}

    def message_status(self, *, provider_message_id: str) -> dict:
        return {"provider_message_id": provider_message_id, "status": "unavailable", "provider": "gmail"}

    def list_since(self, *, history_id: str = "") -> list[InboundEmail]:
        return []

    def get_message(self, *, provider_message_id: str) -> InboundEmail | None:
        return None


class OutlookEmailProvider:
    def health(self) -> EmailHealth:
        return EmailHealth(
            provider="outlook",
            is_mock=False,
            connected=False,
            reason="Outlook is a protocol stub in this batch.",
            state="NOT_CONFIGURED",
        )

    def send(self, *, to: str, subject: str, body: str, thread_id: str = "") -> EmailSendResult:
        return EmailSendResult(
            ok=False,
            provider="outlook",
            is_mock=False,
            status="FAILED",
            reason="Outlook is not implemented.",
            retryable=False,
        )

    def reply(self, *, to: str, subject: str, body: str, thread_id: str) -> EmailSendResult:
        return self.send(to=to, subject=subject, body=body, thread_id=thread_id)

    def thread_lookup(self, *, thread_id: str) -> dict:
        return {"thread_id": thread_id, "messages": [], "provider": "outlook", "is_mock": False}

    def message_status(self, *, provider_message_id: str) -> dict:
        return {"provider_message_id": provider_message_id, "status": "unavailable", "provider": "outlook"}

    def list_since(self, *, history_id: str = "") -> list[InboundEmail]:
        return []

    def get_message(self, *, provider_message_id: str) -> InboundEmail | None:
        return None


@dataclass
class GmailEmailProvider:
    access_token: str
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str = ""
    http_post: object | None = None
    http_get: object | None = None

    def health(self) -> EmailHealth:
        connected = bool(self.access_token)
        state = "CONNECTED" if connected else "NOT_CONFIGURED"
        if self.last_error and not connected:
            state = "ERROR"
        return EmailHealth(
            provider="gmail",
            is_mock=False,
            connected=connected,
            reason="Gmail API token present." if connected else "Gmail access token is missing.",
            state=state,
            last_success_at=self.last_success_at,
            last_failure_at=self.last_failure_at,
            last_error_summary=self.last_error,
        )

    def send(self, *, to: str, subject: str, body: str, thread_id: str = "") -> EmailSendResult:
        return self._submit(to=to, subject=subject, body=body, thread_id=thread_id)

    def reply(self, *, to: str, subject: str, body: str, thread_id: str) -> EmailSendResult:
        return self._submit(to=to, subject=subject, body=body, thread_id=thread_id)

    def thread_lookup(self, *, thread_id: str) -> dict:
        return {"thread_id": thread_id, "messages": [], "provider": "gmail", "is_mock": False}

    def message_status(self, *, provider_message_id: str) -> dict:
        return {"provider_message_id": provider_message_id, "status": "unknown", "provider": "gmail"}

    def list_since(self, *, history_id: str = "") -> list[InboundEmail]:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        params: dict[str, str] = {"userId": "me"}
        url = "https://gmail.googleapis.com/gmail/v1/users/me/history"
        query = {"startHistoryId": history_id} if history_id else {}
        getter = self.http_get or httpx.get
        try:
            response = getter(url, headers=headers, params=query, timeout=20.0)
        except Exception as exc:  # noqa: BLE001
            self.last_failure_at = datetime.now(UTC)
            self.last_error = str(exc)[:400]
            return []
        if response.status_code >= 400:
            self.last_failure_at = datetime.now(UTC)
            self.last_error = f"Gmail history {response.status_code}"
            return []
        payload = response.json() if hasattr(response, "json") else json.loads(response.text)
        messages: list[InboundEmail] = []
        for history in payload.get("history") or []:
            for added in history.get("messagesAdded") or []:
                message = added.get("message") or {}
                message_id = str(message.get("id") or "")
                if not message_id:
                    continue
                fetched = self.get_message(provider_message_id=message_id)
                if fetched is not None:
                    messages.append(fetched)
        if not history_id:
            listed = getter(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=headers,
                params={"q": "in:inbox", "maxResults": 20},
                timeout=20.0,
            )
            if getattr(listed, "status_code", 200) < 400:
                listed_payload = listed.json() if hasattr(listed, "json") else json.loads(listed.text)
                for item in listed_payload.get("messages") or []:
                    fetched = self.get_message(provider_message_id=str(item.get("id") or ""))
                    if fetched is not None:
                        messages.append(fetched)
        _ = base64, params
        self.last_success_at = datetime.now(UTC)
        self.last_error = ""
        return messages

    def get_message(self, *, provider_message_id: str) -> InboundEmail | None:
        if not provider_message_id:
            return None
        getter = self.http_get or httpx.get
        response = getter(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{provider_message_id}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            params={"format": "full"},
            timeout=20.0,
        )
        if getattr(response, "status_code", 200) >= 400:
            return None
        payload = response.json() if hasattr(response, "json") else {}
        headers = {item.get("name"): item.get("value") for item in (payload.get("payload") or {}).get("headers") or []}
        body = _gmail_plain_text(payload)
        return InboundEmail(
            provider_message_id=str(payload.get("id") or provider_message_id),
            thread_id=str(payload.get("threadId") or ""),
            from_addr=str(headers.get("From") or ""),
            to_addrs=[str(headers.get("To") or "")],
            subject=str(headers.get("Subject") or ""),
            body_text=body,
            received_at=datetime.now(UTC),
            history_id=str(payload.get("historyId") or ""),
        )

    def _submit(self, *, to: str, subject: str, body: str, thread_id: str) -> EmailSendResult:
        raw = _rfc822(to=to, subject=subject, body=body).encode("utf-8")
        encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        payload = {"raw": encoded}
        if thread_id:
            payload["threadId"] = thread_id
        poster = self.http_post or httpx.post
        try:
            response = poster(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
                content=json.dumps(payload),
                timeout=20.0,
            )
        except Exception as exc:  # noqa: BLE001
            self.last_failure_at = datetime.now(UTC)
            self.last_error = str(exc)[:400]
            return EmailSendResult(
                ok=False,
                provider="gmail",
                is_mock=False,
                status="RETRYING",
                reason=str(exc)[:400],
                retryable=True,
            )
        status_code = getattr(response, "status_code", 500)
        if status_code == 429 or status_code >= 500:
            self.last_failure_at = datetime.now(UTC)
            self.last_error = f"Gmail send {status_code}"
            return EmailSendResult(
                ok=False,
                provider="gmail",
                is_mock=False,
                status="RETRYING",
                reason=f"Gmail send {status_code}",
                retryable=True,
            )
        if status_code >= 400:
            self.last_failure_at = datetime.now(UTC)
            self.last_error = f"Gmail send {status_code}"
            return EmailSendResult(
                ok=False,
                provider="gmail",
                is_mock=False,
                status="FAILED",
                reason=f"Gmail send {status_code}",
                retryable=False,
            )
        data = response.json() if hasattr(response, "json") else {}
        self.last_success_at = datetime.now(UTC)
        self.last_error = ""
        return EmailSendResult(
            ok=True,
            provider="gmail",
            is_mock=False,
            provider_message_id=str(data.get("id") or f"gmail-{uuid4()}"),
            thread_id=str(data.get("threadId") or thread_id or f"thread-{uuid4()}"),
            status="sent",
            reason="Gmail accepted the message.",
        )


def _rfc822(*, to: str, subject: str, body: str) -> str:
    return f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"


def _gmail_plain_text(payload: dict) -> str:
    body = ((payload.get("payload") or {}).get("body") or {}).get("data")
    if body:
        padded = body + "=" * (-len(body) % 4)
        try:
            return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
        except (ValueError, UnicodeError):
            return ""
    parts = (payload.get("payload") or {}).get("parts") or []
    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = (part.get("body") or {}).get("data")
            if data:
                padded = data + "=" * (-len(data) % 4)
                try:
                    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
                except (ValueError, UnicodeError):
                    return ""
    return str(payload.get("snippet") or "")


def get_email_provider(db: Session | None = None, tenant_id: UUID | None = None) -> EmailProvider:
    settings = get_settings()
    mode = (settings.email_provider or "mock").strip().lower()
    if mode == "outlook":
        return OutlookEmailProvider()
    if mode == "gmail":
        if db is None or tenant_id is None:
            return DisconnectedGmailProvider()
        # Circular: provider_accounts builds a live Gmail client from this module.
        from app.services.provider_accounts import gmail_provider_for_tenant

        return gmail_provider_for_tenant(db, tenant_id)
    return MockEmailProvider()
