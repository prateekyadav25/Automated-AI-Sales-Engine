from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class FinanceHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    state: str = "NOT_CONFIGURED"


@dataclass(frozen=True)
class FinanceInvoice:
    external_id: str
    status: str
    amount: Decimal | None = None


@dataclass(frozen=True)
class FinanceSnapshot:
    past_due: bool | None
    payment_status: str | None
    provider: str
    is_mock: bool
    available: bool
    evidence: str
    outstanding_balance: Decimal | None = None
    days_past_due: int | None = None
    overdue_count: int | None = None
    freshness_state: str = "NOT_CONFIGURED"


class FinanceProvider(Protocol):
    def health(self) -> FinanceHealth: ...

    def snapshot(self, *, account_name: str) -> FinanceSnapshot: ...

    def get_invoices(self, *, account_name: str) -> list[FinanceInvoice]: ...

    def get_outstanding_balance(self, *, account_name: str) -> Decimal | None: ...

    def get_payment_status(self, *, account_name: str) -> str | None: ...

    def get_subscription_value(self, *, account_name: str) -> Decimal | None: ...

    def get_contract_value(self, *, account_name: str) -> Decimal | None: ...

    def get_credit_status(self, *, account_name: str) -> str | None: ...


class UnavailableFinanceProvider:
    def health(self) -> FinanceHealth:
        return FinanceHealth(
            provider="finance",
            is_mock=False,
            connected=False,
            reason="No finance or billing provider is configured.",
            state="NOT_CONFIGURED",
        )

    def snapshot(self, *, account_name: str) -> FinanceSnapshot:
        _ = account_name
        return FinanceSnapshot(
            past_due=None,
            payment_status=None,
            provider="finance",
            is_mock=False,
            available=False,
            evidence="Payment health is UNAVAILABLE.",
        )

    def get_invoices(self, *, account_name: str) -> list[FinanceInvoice]:
        _ = account_name
        return []

    def get_outstanding_balance(self, *, account_name: str) -> Decimal | None:
        return None

    def get_payment_status(self, *, account_name: str) -> str | None:
        return None

    def get_subscription_value(self, *, account_name: str) -> Decimal | None:
        return None

    def get_contract_value(self, *, account_name: str) -> Decimal | None:
        return None

    def get_credit_status(self, *, account_name: str) -> str | None:
        return None


class GenericFinanceWebhookProvider(UnavailableFinanceProvider):
    def __init__(self, *, live: bool, provider: str = "finance"):
        self.live = live
        self.provider_name = provider

    def health(self) -> FinanceHealth:
        if self.live:
            return FinanceHealth(
                provider=self.provider_name,
                is_mock=False,
                connected=True,
                reason=f"Generic signed {self.provider_name} webhook is live for this tenant.",
                state="LIVE",
            )
        return FinanceHealth(
            provider=self.provider_name,
            is_mock=False,
            connected=False,
            reason=f"{self.provider_name} webhook is registered but LIVE mode is off.",
            state="NOT_CONFIGURED",
        )


class StripeFinanceProvider(UnavailableFinanceProvider):
    def health(self) -> FinanceHealth:
        return FinanceHealth(
            provider="stripe",
            is_mock=False,
            connected=False,
            reason="Stripe HTTP is not configured. Use the generic finance webhook.",
            state="NOT_CONFIGURED",
        )


class GenericERPProvider(GenericFinanceWebhookProvider):
    def __init__(self, *, live: bool):
        super().__init__(live=live, provider="erp")


def get_finance_provider(db: Session | None = None, tenant_id: UUID | None = None) -> FinanceProvider:
    if db is None or tenant_id is None:
        return UnavailableFinanceProvider()
    from app.services.autopilot_settings import get_or_create_settings

    settings = get_or_create_settings(db, tenant_id=tenant_id)
    if settings.finance_live_enabled:
        return GenericFinanceWebhookProvider(live=True)
    return UnavailableFinanceProvider()


def get_erp_provider(db: Session | None = None, tenant_id: UUID | None = None) -> FinanceProvider:
    if db is None or tenant_id is None:
        return GenericERPProvider(live=False)
    from app.services.autopilot_settings import get_or_create_settings

    settings = get_or_create_settings(db, tenant_id=tenant_id)
    return GenericERPProvider(live=settings.erp_live_enabled)
