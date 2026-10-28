from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Account, Activity, Customer, Lead, Opportunity, Renewal
from app.models.identity import Team, TeamMember, User
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


def list_lead_assignees(db: Session, tenant_id: UUID) -> list[dict[str, str | UUID]]:
    rows = db.execute(
        select(User, Team.name)
        .join(TeamMember, TeamMember.user_id == User.id)
        .join(Team, Team.id == TeamMember.team_id)
        .where(User.tenant_id == tenant_id, User.is_active.is_(True), Team.tenant_id == tenant_id)
        .order_by(User.name.asc())
    ).all()
    people: dict[UUID, dict[str, str | UUID]] = {}
    for user, team_name in rows:
        people.setdefault(user.id, {"id": user.id, "name": user.name, "email": user.email, "team_name": team_name})
    if people:
        return list(people.values())
    users = db.scalars(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)).order_by(User.name.asc())).all()
    return [{"id": user.id, "name": user.name, "email": user.email, "team_name": ""} for user in users]


def assign_lead(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    owner_id: UUID | None,
    correlation_id: str,
) -> None:
    if owner_id is not None and owner_id not in {row["id"] for row in list_lead_assignees(db, tenant_id)}:
        raise ValueError("Choose an active team member.")
    previous = lead.owner_id
    lead.owner_id = owner_id
    lead.updated_by = actor_id
    owner = db.scalar(select(User).where(User.id == owner_id, User.tenant_id == tenant_id)) if owner_id else None
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="assigned",
        title=f"Assigned to {owner.name}" if owner else "Assignment cleared",
    )
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="lead.assign",
        entity_type="lead",
        entity_id=str(lead.id),
        before={"owner_id": str(previous) if previous else ""},
        after={"owner_id": str(owner_id) if owner_id else ""},
        correlation_id=correlation_id,
    )


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
    historical_fixture: bool = False,
) -> tuple[Opportunity, Customer, Renewal]:
    if not historical_fixture:
        raise ValueError("Historical activation is closed. Use the accepted-quote close-won decision.")
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
        arr=existing.arr if existing else Decimal("0"),
    )
    if existing:
        customer.opportunity_id = opp.id
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
