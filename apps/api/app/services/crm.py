from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Account, Activity, Customer, Lead, Opportunity, Renewal
from app.services.audit import emit_event, write_audit
from app.services.idempotency import lock_row
from app.services.ml.history import record_opportunity_fields
from app.services.query import get_owned

STAGE_PROBABILITY = {
    "qualification": 10,
    "discovery": 20,
    "solution_fit": 30,
    "technical_discovery": 35,
    "demo": 40,
    "business_case": 50,
    "proposal": 60,
    "commercial_discussion": 65,
    "negotiation": 70,
    "procurement": 75,
    "legal": 80,
    "commit": 90,
    "closed_won": 100,
    "closed_lost": 0,
}


def add_activity(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    entity_type: str,
    entity_id: str,
    activity_type: str,
    title: str,
    body: str = "",
    actor_type: str = "human",
) -> Activity:
    row = Activity(
        tenant_id=tenant_id,
        created_by=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        activity_type=activity_type,
        title=title,
        body=body,
        actor_type=actor_type,
    )
    db.add(row)
    return row


def close_won(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    opportunity_id: UUID,
    correlation_id: str = "",
) -> tuple[Opportunity, Customer, Renewal]:
    opp = lock_row(db, Opportunity, tenant_id, opportunity_id) or get_owned(db, Opportunity, tenant_id, opportunity_id)

    record_opportunity_fields(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        opportunity_id=opp.id,
        changes={"stage": (opp.stage, "closed_won"), "probability": (opp.probability, 100)},
    )
    opp.stage = "closed_won"
    opp.probability = 100
    account = get_owned(db, Account, tenant_id, opp.account_id)
    account.ownership = "customer"
    existing = db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.account_id == account.id,
            Customer.deleted_at.is_(None),
        )
    )
    customer = existing or Customer(
        tenant_id=tenant_id,
        created_by=actor_id,
        account_id=account.id,
        opportunity_id=opp.id,
        status="onboarding",
        lifecycle_state="NEW_CUSTOMER",
        arr=opp.amount or Decimal("0"),
    )
    if existing:
        customer.opportunity_id = opp.id
        customer.arr = opp.amount or customer.arr
    else:
        db.add(customer)
        db.flush()
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="opportunity",
        entity_id=str(opp.id),
        activity_type="stage_change",
        title="Closed won",
        body="Customer and renewal stub created.",
    )
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="opportunity.closed_won",
        entity_type="opportunity",
        entity_id=str(opp.id),
        after={"customer_id": str(customer.id)},
        correlation_id=correlation_id,
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="deal.won",
        entity_type="opportunity",
        entity_id=str(opp.id),
        payload={"account_id": str(account.id), "customer_id": str(customer.id)},
        correlation_id=correlation_id,
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="customer.created",
        entity_type="customer",
        entity_id=str(customer.id),
        payload={"account_id": str(account.id)},
        correlation_id=correlation_id,
    )
    from app.services.post_sale import activate_customer, ensure_renewal

    activate_customer(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        customer=customer,
        account=account,
        opportunity=opp,
        correlation_id=correlation_id,
    )
    renewal = ensure_renewal(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, account=account, contract=None)
    return opp, customer, renewal


def latest_lead_score(db: Session, lead: Lead):
    from app.models.crm import LeadScore

    return db.scalar(
        select(LeadScore)
        .where(LeadScore.lead_id == lead.id, LeadScore.tenant_id == lead.tenant_id)
        .order_by(LeadScore.created_at.desc())
    )
