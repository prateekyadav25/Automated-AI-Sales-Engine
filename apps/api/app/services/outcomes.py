from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.crm import Customer, Opportunity, Renewal
from app.models.post_sale import ExpansionRecommendation
from app.services.audit import emit_event, write_audit
from app.services.crm import add_activity
from app.services.ml.history import record_opportunity_fields
from app.services.ml.labels import ResolvedLabel, upsert_outcome
from app.services.ml.timeutil import now_utc
from app.services.query import get_owned

LOSS_REASONS = {
    "pricing",
    "competition",
    "timing",
    "budget",
    "product_fit",
    "relationship",
    "procurement",
    "legal",
    "no_decision",
    "other",
}
CHURN_REASONS = {
    "adoption",
    "support",
    "price",
    "budget",
    "product_fit",
    "competitor",
    "strategy",
    "business_closure",
    "other",
}


def close_lost(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    opportunity_id: UUID,
    reason: str,
    note: str = "",
) -> Opportunity:
    if reason not in LOSS_REASONS:
        raise ValueError("Unknown closed-lost reason")
    opp = get_owned(db, Opportunity, tenant_id, opportunity_id)
    record_opportunity_fields(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        opportunity_id=opp.id,
        changes={"stage": (opp.stage, "closed_lost"), "loss_reason": (opp.loss_reason, reason)},
    )
    opp.stage = "closed_lost"
    opp.probability = 0
    opp.loss_reason = reason
    upsert_outcome(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        task_key="OPPORTUNITY_WIN",
        entity_type="opportunity",
        entity_id=str(opp.id),
        resolved=ResolvedLabel("NEGATIVE", 0, now_utc(), {"reason": reason, "note": note}),
    )
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="opportunity.closed_lost",
        entity_type="opportunity",
        entity_id=str(opp.id),
        after={"reason": reason},
    )
    emit_event(db, tenant_id=tenant_id, event_type="deal.lost", entity_type="opportunity", entity_id=str(opp.id), payload={"reason": reason})
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="opportunity",
        entity_id=str(opp.id),
        activity_type="stage_change",
        title="Closed lost",
        body=reason,
    )
    return opp


def mark_churned(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    customer_id: UUID,
    reason: str,
) -> Customer:
    if reason not in CHURN_REASONS:
        raise ValueError("Unknown churn reason")
    customer = get_owned(db, Customer, tenant_id, customer_id)
    customer.status = "churned"
    customer.churn_reason = reason
    upsert_outcome(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        task_key="CUSTOMER_CHURN",
        entity_type="customer",
        entity_id=str(customer.id),
        resolved=ResolvedLabel("POSITIVE", 1, now_utc(), {"reason": reason}),
    )
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="customer.churned",
        entity_type="customer",
        entity_id=str(customer.id),
        after={"reason": reason},
    )
    emit_event(db, tenant_id=tenant_id, event_type="customer.churned", entity_type="customer", entity_id=str(customer.id), payload={"reason": reason})
    return customer


def mark_renewed(db: Session, *, tenant_id: UUID, actor_id: UUID, renewal_id: UUID) -> Renewal:
    renewal = get_owned(db, Renewal, tenant_id, renewal_id)
    renewal.status = "renewed"
    upsert_outcome(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        task_key="CUSTOMER_RENEWAL",
        entity_type="customer",
        entity_id=str(renewal.customer_id),
        resolved=ResolvedLabel("POSITIVE", 1, now_utc(), {"renewal_id": str(renewal.id)}),
    )
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="renewal.completed", entity_type="renewal", entity_id=str(renewal.id))
    return renewal


def record_expansion_outcome(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    recommendation_id: UUID,
    status: str,
    value: Decimal | None = None,
    product: str = "",
) -> ExpansionRecommendation:
    rec = get_owned(db, ExpansionRecommendation, tenant_id, recommendation_id)
    rec.outcome_status = status
    rec.outcome_value = value
    rec.outcome_product = product
    if status in {"won", "converted"}:
        rec.status = "won"
        upsert_outcome(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            task_key="EXPANSION_PROPENSITY",
            entity_type="customer",
            entity_id=str(rec.customer_id),
            resolved=ResolvedLabel("POSITIVE", 1, now_utc(), {"recommendation_id": str(rec.id)}),
        )
    return rec
