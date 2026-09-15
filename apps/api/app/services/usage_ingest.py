import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.crm import Customer
from app.models.post_sale import Contract, ContractLine, ProductUsageSnapshot
from app.models.signals import CustomerSignal, UsageEvent, UsageRollup
from app.services.autopilot_settings import get_or_create_settings
from app.services.entity_mapping import resolve_customer
from app.services.intelligence_state import mark_dirty, touch_watermark
from app.services.provider_metrics import USAGE_EVENTS

USAGE_EVENT_TYPES = {
    "user.active",
    "user.login",
    "feature.used",
    "workflow.executed",
    "api.requested",
    "seat.assigned",
    "seat.active",
    "capacity.used",
    "license.limit_approaching",
    "product.error",
}


def aware_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _parse_dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return aware_dt(value) or datetime.now(UTC)
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return aware_dt(parsed) or datetime.now(UTC)
    except ValueError:
        return datetime.now(UTC)


def licensed_seats(db: Session, tenant_id: UUID, customer: Customer) -> int | None:
    contract = db.scalar(
        select(Contract).where(
            Contract.tenant_id == tenant_id,
            Contract.customer_id == customer.id,
            Contract.deleted_at.is_(None),
        )
    )
    if contract is None:
        return None
    lines = db.scalars(select(ContractLine).where(ContractLine.contract_id == contract.id, ContractLine.deleted_at.is_(None))).all()
    seats = [int(line.quantity) for line in lines if line.quantity and line.quantity > 0]
    return sum(seats) if seats else None


def freshness_state(last_event_at: datetime | None, hours: int) -> str:
    observed = aware_dt(last_event_at)
    if observed is None:
        return "NOT_CONFIGURED"
    if datetime.now(UTC) - observed > timedelta(hours=max(hours, 1)):
        return "STALE"
    return "LIVE"


def _trend(current: int, previous: int) -> str:
    if previous <= 0:
        return "stable"
    if current > previous + max(1, previous // 10):
        return "improving"
    if current < previous - max(1, previous // 10):
        return "declining"
    return "stable"


def refresh_rollups(db: Session, *, tenant_id: UUID, actor_id: UUID | None, customer: Customer) -> UsageRollup:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = db.scalars(
        select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.customer_id == customer.id,
            UsageEvent.deleted_at.is_(None),
        )
    ).all()
    last = max((aware_dt(row.observed_at) for row in events if row.observed_at), default=None)
    state = freshness_state(last, settings.usage_freshness_hours)

    def unique_users(since: datetime) -> set[str]:
        return {
            row.actor_external_id or str(row.id)
            for row in events
            if row.event_type in {"user.active", "user.login", "seat.active"}
            and aware_dt(row.observed_at) is not None
            and aware_dt(row.observed_at) >= since
        }

    dau = len(unique_users(now - timedelta(days=1)))
    wau = len(unique_users(now - timedelta(days=7)))
    mau = len(unique_users(now - timedelta(days=30)))
    seats_active = len(
        {
            row.actor_external_id or str(row.id)
            for row in events
            if row.event_type in {"seat.active", "seat.assigned", "user.active"}
            and aware_dt(row.observed_at) is not None
            and aware_dt(row.observed_at) >= now - timedelta(days=30)
        }
    )
    licensed = licensed_seats(db, tenant_id, customer)
    utilization = None
    if licensed and licensed > 0:
        utilization = int(round(seats_active / licensed * 100))
    features = {row.feature_key for row in events if row.event_type == "feature.used" and row.feature_key}
    depth = sum(1 for row in events if row.event_type == "feature.used")
    prev_week = len(unique_users(now - timedelta(days=14))) - wau
    prev_month_users = len(unique_users(now - timedelta(days=60))) - mau
    row = db.scalar(
        select(UsageRollup).where(
            UsageRollup.tenant_id == tenant_id,
            UsageRollup.customer_id == customer.id,
            UsageRollup.grain == "daily",
            UsageRollup.period_start == day_start,
            UsageRollup.deleted_at.is_(None),
        )
    )
    evidence = f"DAU={dau} WAU={wau} MAU={mau} seats={seats_active}/{licensed or 'unknown'} {state}"
    payload = dict(
        account_id=customer.account_id,
        grain="daily",
        period_start=day_start,
        dau=dau,
        wau=wau,
        mau=mau,
        seats_licensed=licensed,
        seats_active=seats_active,
        utilization_pct=utilization,
        feature_breadth=len(features),
        feature_depth=depth,
        last_activity_at=last,
        trend_7d=_trend(wau, max(prev_week, 0)),
        trend_30d=_trend(mau, max(prev_month_users, 0)),
        trend_90d="stable",
        freshness_state=state,
        is_mock=False,
        evidence=evidence,
    )
    if row is None:
        row = UsageRollup(tenant_id=tenant_id, created_by=actor_id, customer_id=customer.id, **payload)
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    db.flush()
    persist_usage_card(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, rollup=row)
    return row


def persist_usage_card(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    customer: Customer,
    rollup: UsageRollup,
) -> ProductUsageSnapshot:
    latest = db.scalar(
        select(ProductUsageSnapshot)
        .where(ProductUsageSnapshot.tenant_id == tenant_id, ProductUsageSnapshot.customer_id == customer.id)
        .order_by(ProductUsageSnapshot.created_at.desc())
    )
    if latest is not None and latest.is_mock is False and latest.last_activity_at == rollup.last_activity_at:
        latest.active_users = rollup.dau
        latest.seats_licensed = rollup.seats_licensed
        latest.seats_used = rollup.seats_active
        latest.feature_breadth = rollup.feature_breadth
        latest.depth = rollup.feature_depth
        latest.trend = rollup.trend_30d
        latest.evidence = rollup.evidence
        latest.is_mock = False
        latest.provider = "usage"
        return latest
    card = ProductUsageSnapshot(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer.id,
        account_id=customer.account_id,
        period_start=datetime.now(UTC).date(),
        active_users=rollup.dau,
        seats_licensed=rollup.seats_licensed,
        seats_used=rollup.seats_active,
        frequency=rollup.wau,
        feature_breadth=rollup.feature_breadth,
        depth=rollup.feature_depth,
        trend=rollup.trend_30d,
        last_activity_at=rollup.last_activity_at,
        provider="usage",
        is_mock=False,
        evidence=rollup.evidence,
    )
    db.add(card)
    db.flush()
    return card


def latest_rollup(db: Session, tenant_id: UUID, customer_id: UUID) -> UsageRollup | None:
    return db.scalar(
        select(UsageRollup)
        .where(
            UsageRollup.tenant_id == tenant_id,
            UsageRollup.customer_id == customer_id,
            UsageRollup.deleted_at.is_(None),
        )
        .order_by(UsageRollup.period_start.desc())
    )


def ingest_usage_payload(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    payload: dict,
    external_id: str,
) -> str:
    event_type = str(payload.get("event_type") or payload.get("type") or payload.get("kind") or "")
    if event_type not in USAGE_EVENT_TYPES:
        return "ignored_type"
    existing = db.scalar(
        select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.provider == "usage",
            UsageEvent.external_id == external_id,
            UsageEvent.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return "duplicate"
    customer = resolve_customer(db, tenant_id=tenant_id, actor_id=actor_id, provider="usage", payload=payload)
    observed = _parse_dt(payload.get("observed_at") or payload.get("occurred_at"))
    bounded = json.dumps({key: payload.get(key) for key in list(payload)[:20]}, default=str)[:4000]
    event = UsageEvent(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer.id if customer else None,
        account_id=customer.account_id if customer else None,
        provider="usage",
        external_id=external_id,
        event_type=event_type,
        actor_external_id=str(payload.get("user_id") or payload.get("actor_id") or ""),
        feature_key=str(payload.get("feature") or payload.get("feature_key") or ""),
        quantity=int(payload.get("quantity") or 1),
        observed_at=observed,
        payload_json=bounded,
        is_mock=False,
    )
    db.add(event)
    db.add(
        CustomerSignal(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=customer.id if customer else None,
            account_id=customer.account_id if customer else None,
            signal_type=event_type,
            signal_category="USAGE",
            source_provider="usage",
            external_reference=external_id,
            value_numeric=None,
            value_text=event.feature_key or event.actor_external_id,
            value_json=bounded,
            observed_at=observed,
            received_at=datetime.now(UTC),
            freshness_state="LIVE",
            is_mock=False,
            is_verified=customer is not None,
            schema_version="1",
        )
    )
    db.flush()
    USAGE_EVENTS.labels(provider="usage").inc()
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    settings.usage_live_enabled = True
    if customer is not None:
        refresh_rollups(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer)
        mark_dirty(db, tenant_id=tenant_id, actor_id=actor_id, customer_id=customer.id)
    mapped = db.scalar(select(func.count()).where(UsageEvent.tenant_id == tenant_id, UsageEvent.customer_id.is_not(None))) or 0
    touch_watermark(db, tenant_id=tenant_id, provider="usage", cursor=external_id, connected_customers=int(mapped))
    return "ingested" if customer is not None else "unmapped"
