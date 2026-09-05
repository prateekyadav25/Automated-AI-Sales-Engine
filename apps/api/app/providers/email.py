from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class EmailHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str


@dataclass(frozen=True)
class EmailSendResult:
    ok: bool
    provider: str
    is_mock: bool
    provider_message_id: str = ""
    thread_id: str = ""
    status: str = "sent"
    reason: str = ""


class EmailProvider(Protocol):
    def health(self) -> EmailHealth: ...

    def send(self, *, to: str, subject: str, body: str, thread_id: str = "") -> EmailSendResult: ...

    def reply(self, *, to: str, subject: str, body: str, thread_id: str) -> EmailSendResult: ...

    def thread_lookup(self, *, thread_id: str) -> dict: ...

    def message_status(self, *, provider_message_id: str) -> dict: ...


class MockEmailProvider:
    def health(self) -> EmailHealth:
        return EmailHealth(
            provider="mock-email",
            is_mock=True,
            connected=True,
            reason="Labeled mock. Approved sends persist a provider id. Live Gmail is not configured.",
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


def get_email_provider() -> EmailProvider:
    return MockEmailProvider()
