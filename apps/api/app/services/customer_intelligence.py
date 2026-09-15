from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Customer, Renewal
from app.services.autopilot_settings import get_or_create_settings
from app.services.customer_health import recalculate
from app.services.customer_risk import detect_risks
from app.services.expansion import detect_expansion
from app.services.intelligence_state import dirty_customers, mark_clean
from app.services.renewal import score_readiness


def refresh_customer_intelligence(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer) -> str:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    try:
        if settings.customer_health_enabled:
            recalculate(db, tenant_id, customer, actor_id)
    except Exception:  # noqa: BLE001
        pass
    try:
        if settings.customer_success_enabled:
            detect_risks(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer)
    except Exception:  # noqa: BLE001
        pass
    try:
        if settings.expansion_enabled or settings.upsell_enabled or settings.cross_sell_enabled:
            detect_expansion(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, settings=settings)
    except Exception:  # noqa: BLE001
        pass
    try:
        renewal = db.scalar(
            select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None))
        )
        if renewal and settings.renewal_enabled:
            score_readiness(db, tenant_id=tenant_id, customer=customer, renewal=renewal)
    except Exception:  # noqa: BLE001
        pass
    mark_clean(db, tenant_id=tenant_id, customer_id=customer.id)
    return "refreshed"


def process_dirty_customers(db: Session, *, tenant_id: UUID, actor_id: UUID) -> int:
    count = 0
    for customer in dirty_customers(db, tenant_id):
        refresh_customer_intelligence(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer)
        count += 1
    return count


def rebuild_health(db: Session, *, tenant_id: UUID, actor_id: UUID, customer_id: UUID | None = None) -> int:
    if customer_id is not None:
        customer = db.scalar(select(Customer).where(Customer.tenant_id == tenant_id, Customer.id == customer_id, Customer.deleted_at.is_(None)))
        if customer is None:
            return 0
        recalculate(db, tenant_id, customer, actor_id)
        return 1
    rows = db.scalars(select(Customer).where(Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None))).all()
    for customer in rows:
        recalculate(db, tenant_id, customer, actor_id)
    return len(rows)
