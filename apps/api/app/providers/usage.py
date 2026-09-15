from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class UsageHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    state: str = "MOCK"


@dataclass(frozen=True)
class UsageEvent:
    kind: str
    count: int = 0


@dataclass(frozen=True)
class UsageSnapshot:
    adoption: int
    usage: int
    provider: str
    is_mock: bool
    evidence: str
    active_users: int | None = None
    seats_licensed: int | None = None
    seats_used: int | None = None
    frequency: int | None = None
    feature_breadth: int | None = None
    depth: int | None = None
    last_activity_at: datetime | None = None
    events: tuple[UsageEvent, ...] = ()
    trend: str = "stable"
    freshness_state: str = "MOCK"


class ProductUsageProvider(Protocol):
    def health(self) -> UsageHealth: ...

    def snapshot(self, *, account_name: str) -> UsageSnapshot: ...

    def get_customer_usage(self, *, account_name: str) -> UsageSnapshot: ...

    def get_active_users(self, *, account_name: str) -> int | None: ...

    def get_feature_usage(self, *, account_name: str) -> int | None: ...

    def get_capacity_usage(self, *, account_name: str) -> int | None: ...

    def get_last_activity(self, *, account_name: str) -> datetime | None: ...

    def get_usage_trend(self, *, account_name: str) -> str: ...


class MockProductUsageProvider:
    def health(self) -> UsageHealth:
        return UsageHealth(
            provider="mock-usage",
            is_mock=True,
            connected=True,
            reason="Labeled mock. Not a product-analytics feed.",
            state="MOCK",
        )

    def snapshot(self, *, account_name: str) -> UsageSnapshot:
        seed = sum(ord(char) for char in account_name) % 21
        return UsageSnapshot(
            adoption=40 + seed,
            usage=35 + seed,
            provider="mock-usage",
            is_mock=True,
            evidence=f"Mock usage card for {account_name}. Not a product-analytics feed.",
            active_users=8 + seed // 3,
            seats_licensed=None,
            seats_used=None,
            frequency=12 + seed // 4,
            feature_breadth=4 + seed // 7,
            depth=20 + seed,
            last_activity_at=datetime.now(UTC),
            events=(
                UsageEvent(kind="login", count=20 + seed),
                UsageEvent(kind="active_user", count=8 + seed // 3),
                UsageEvent(kind="feature_use", count=4 + seed // 7),
            ),
            trend="stable",
            freshness_state="MOCK",
        )

    def get_customer_usage(self, *, account_name: str) -> UsageSnapshot:
        return self.snapshot(account_name=account_name)

    def get_active_users(self, *, account_name: str) -> int | None:
        return self.snapshot(account_name=account_name).active_users

    def get_feature_usage(self, *, account_name: str) -> int | None:
        return self.snapshot(account_name=account_name).feature_breadth

    def get_capacity_usage(self, *, account_name: str) -> int | None:
        return None

    def get_last_activity(self, *, account_name: str) -> datetime | None:
        return self.snapshot(account_name=account_name).last_activity_at

    def get_usage_trend(self, *, account_name: str) -> str:
        return "stable"


class GenericUsageWebhookProvider:
    def __init__(self, *, live: bool):
        self.live = live

    def health(self) -> UsageHealth:
        if self.live:
            return UsageHealth(
                provider="usage",
                is_mock=False,
                connected=True,
                reason="Generic signed usage webhook is live for this tenant.",
                state="LIVE",
            )
        return UsageHealth(
            provider="usage",
            is_mock=False,
            connected=False,
            reason="Usage webhook route exists but LIVE mode is off or no events have arrived.",
            state="NOT_CONFIGURED",
        )

    def snapshot(self, *, account_name: str) -> UsageSnapshot:
        _ = account_name
        return UsageSnapshot(
            adoption=0,
            usage=0,
            provider="usage",
            is_mock=False,
            evidence="Read usage_rollups. This provider does not invent DAU.",
            freshness_state="NOT_CONFIGURED" if not self.live else "LIVE",
        )

    def get_customer_usage(self, *, account_name: str) -> UsageSnapshot:
        return self.snapshot(account_name=account_name)

    def get_active_users(self, *, account_name: str) -> int | None:
        return None

    def get_feature_usage(self, *, account_name: str) -> int | None:
        return None

    def get_capacity_usage(self, *, account_name: str) -> int | None:
        return None

    def get_last_activity(self, *, account_name: str) -> datetime | None:
        return None

    def get_usage_trend(self, *, account_name: str) -> str:
        return "stable"


def get_usage_provider(db: Session | None = None, tenant_id: UUID | None = None) -> ProductUsageProvider:
    if db is None or tenant_id is None:
        return MockProductUsageProvider()
    from app.services.autopilot_settings import get_or_create_settings

    settings = get_or_create_settings(db, tenant_id=tenant_id)
    if settings.usage_live_enabled:
        return GenericUsageWebhookProvider(live=True)
    return MockProductUsageProvider()
