from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SupportHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    state: str = "NOT_CONFIGURED"


@dataclass(frozen=True)
class SupportTicket:
    external_id: str
    status: str
    severity: str = ""


@dataclass(frozen=True)
class SupportSnapshot:
    open_severe: int | None
    open_total: int | None
    provider: str
    is_mock: bool
    available: bool
    evidence: str
    tickets_30d: int | None = None
    avg_resolution_hours: int | None = None
    escalations: int | None = None
    freshness_state: str = "NOT_CONFIGURED"


class SupportProvider(Protocol):
    def health(self) -> SupportHealth: ...

    def snapshot(self, *, account_name: str) -> SupportSnapshot: ...

    def list_tickets(self, *, account_name: str) -> list[SupportTicket]: ...

    def get_ticket(self, *, ticket_id: str) -> SupportTicket | None: ...

    def get_customer_summary(self, *, account_name: str) -> SupportSnapshot: ...

    def get_open_critical_tickets(self, *, account_name: str) -> int | None: ...

    def get_support_metrics(self, *, account_name: str) -> SupportSnapshot: ...


class UnavailableSupportProvider:
    def health(self) -> SupportHealth:
        return SupportHealth(
            provider="support",
            is_mock=False,
            connected=False,
            reason="No support provider is configured.",
            state="NOT_CONFIGURED",
        )

    def snapshot(self, *, account_name: str) -> SupportSnapshot:
        _ = account_name
        return SupportSnapshot(
            open_severe=None,
            open_total=None,
            provider="support",
            is_mock=False,
            available=False,
            evidence="Support signal is UNAVAILABLE.",
        )

    def list_tickets(self, *, account_name: str) -> list[SupportTicket]:
        _ = account_name
        return []

    def get_ticket(self, *, ticket_id: str) -> SupportTicket | None:
        _ = ticket_id
        return None

    def get_customer_summary(self, *, account_name: str) -> SupportSnapshot:
        return self.snapshot(account_name=account_name)

    def get_open_critical_tickets(self, *, account_name: str) -> int | None:
        return None

    def get_support_metrics(self, *, account_name: str) -> SupportSnapshot:
        return self.snapshot(account_name=account_name)


class GenericSupportWebhookProvider(UnavailableSupportProvider):
    def __init__(self, *, live: bool):
        self.live = live

    def health(self) -> SupportHealth:
        if self.live:
            return SupportHealth(
                provider="support",
                is_mock=False,
                connected=True,
                reason="Generic signed support webhook is live for this tenant.",
                state="LIVE",
            )
        return SupportHealth(
            provider="support",
            is_mock=False,
            connected=False,
            reason="Support webhook is registered but LIVE mode is off.",
            state="NOT_CONFIGURED",
        )


class ZendeskSupportProvider(UnavailableSupportProvider):
    def health(self) -> SupportHealth:
        return SupportHealth(
            provider="zendesk",
            is_mock=False,
            connected=False,
            reason="Zendesk HTTP is not configured. Use the generic support webhook.",
            state="NOT_CONFIGURED",
        )


class FreshdeskSupportProvider(UnavailableSupportProvider):
    def health(self) -> SupportHealth:
        return SupportHealth(
            provider="freshdesk",
            is_mock=False,
            connected=False,
            reason="Freshdesk HTTP is not configured. Use the generic support webhook.",
            state="NOT_CONFIGURED",
        )


class ServiceNowSupportProvider(UnavailableSupportProvider):
    def health(self) -> SupportHealth:
        return SupportHealth(
            provider="servicenow",
            is_mock=False,
            connected=False,
            reason="ServiceNow HTTP is not configured. Use the generic support webhook.",
            state="NOT_CONFIGURED",
        )


def get_support_provider(db: Session | None = None, tenant_id: UUID | None = None) -> SupportProvider:
    if db is None or tenant_id is None:
        return UnavailableSupportProvider()
    from app.services.autopilot_settings import get_or_create_settings

    settings = get_or_create_settings(db, tenant_id=tenant_id)
    if settings.support_live_enabled:
        return GenericSupportWebhookProvider(live=True)
    return UnavailableSupportProvider()
