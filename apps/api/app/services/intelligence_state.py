from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Customer
from app.models.signals import CustomerIntelligenceState, IntegrationWatermark


def mark_dirty(db: Session, *, tenant_id: UUID, actor_id: UUID | None, customer_id: UUID) -> CustomerIntelligenceState:
    row = db.scalar(
        select(CustomerIntelligenceState).where(
            CustomerIntelligenceState.tenant_id == tenant_id,
            CustomerIntelligenceState.customer_id == customer_id,
            CustomerIntelligenceState.deleted_at.is_(None),
        )
    )
    now = datetime.now(UTC)
    if row is None:
        row = CustomerIntelligenceState(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=customer_id,
            dirty=True,
            dirty_at=now,
        )
        db.add(row)
        db.flush()
        return row
    row.dirty = True
    row.dirty_at = now
    return row


def mark_clean(db: Session, *, tenant_id: UUID, customer_id: UUID) -> None:
    row = db.scalar(
        select(CustomerIntelligenceState).where(
            CustomerIntelligenceState.tenant_id == tenant_id,
            CustomerIntelligenceState.customer_id == customer_id,
            CustomerIntelligenceState.deleted_at.is_(None),
        )
    )
    if row is None:
        return
    row.dirty = False
    row.last_recalc_at = datetime.now(UTC)


def dirty_customers(db: Session, tenant_id: UUID) -> list[Customer]:
    states = db.scalars(
        select(CustomerIntelligenceState).where(
            CustomerIntelligenceState.tenant_id == tenant_id,
            CustomerIntelligenceState.dirty.is_(True),
            CustomerIntelligenceState.deleted_at.is_(None),
        )
    ).all()
    if not states:
        return []
    ids = [row.customer_id for row in states]
    return list(
        db.scalars(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.id.in_(ids),
                Customer.deleted_at.is_(None),
            )
        ).all()
    )


def touch_watermark(
    db: Session,
    *,
    tenant_id: UUID,
    provider: str,
    cursor: str = "",
    error: str = "",
    connected_customers: int | None = None,
    stale_customers: int | None = None,
) -> IntegrationWatermark:
    row = db.scalar(
        select(IntegrationWatermark).where(
            IntegrationWatermark.tenant_id == tenant_id,
            IntegrationWatermark.provider == provider,
            IntegrationWatermark.deleted_at.is_(None),
        )
    )
    if row is None:
        row = IntegrationWatermark(tenant_id=tenant_id, provider=provider)
        db.add(row)
    row.last_sync_cursor = cursor or row.last_sync_cursor
    row.last_sync_at = datetime.now(UTC)
    row.last_error = error
    if error:
        row.failed_syncs += 1
    if connected_customers is not None:
        row.connected_customers = connected_customers
    if stale_customers is not None:
        row.stale_customers = stale_customers
    db.flush()
    return row
