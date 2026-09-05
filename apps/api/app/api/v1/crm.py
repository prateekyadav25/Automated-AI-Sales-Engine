from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.crm import ICP, Account, Activity, Contact, Customer, Lead, Opportunity, Task
from app.schemas.common import Envelope, Meta
from app.schemas.crm import (
    AccountContextOut,
    AccountIn,
    AccountOut,
    ActivityOut,
    ContactIn,
    ContactOut,
    CustomerOut,
    ICPIn,
    ICPOut,
    LeadIn,
    LeadOut,
    LeadScoreOut,
    NBAOut,
    OpportunityIn,
    OpportunityOut,
    TaskIn,
    TaskOut,
)
from app.services.audit import emit_event, write_audit
from app.services.crm import STAGE_PROBABILITY, add_activity, close_won, latest_lead_score
from app.services.nba import generate_for_lead, generate_for_opportunity
from app.services.orchestrator import process_pending_events
from app.services.query import get_owned, paginate
from app.services.scoring import score_lead

router = APIRouter(tags=["crm"])


def _lead_out(db: Session, lead: Lead) -> LeadOut:
    score = latest_lead_score(db, lead)
    payload = LeadOut.model_validate(lead)
    if score is not None:
        payload.latest_score = LeadScoreOut.model_validate(score)
    return payload


def _contact_out(db: Session, tenant_id: UUID, row: Contact, names: dict[UUID, str] | None = None) -> ContactOut:
    payload = ContactOut.model_validate(row)
    if row.account_id is None:
        return payload
    if names is not None:
        payload.account_name = names.get(row.account_id)
        return payload
    account = db.scalar(select(Account).where(Account.id == row.account_id, Account.tenant_id == tenant_id))
    payload.account_name = account.name if account else None
    return payload


@router.get("/accounts", response_model=Envelope[list[AccountOut]])
def list_accounts(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("accounts.read"))],
    page: int = 1,
    page_size: int = 25,
    q: str = "",
) -> Envelope[list[AccountOut]]:
    stmt = select(Account).where(Account.tenant_id == ctx.tenant_id, Account.deleted_at.is_(None))
    if q:
        stmt = stmt.where(or_(Account.name.ilike(f"%{q}%"), Account.industry.ilike(f"%{q}%")))
    stmt = stmt.order_by(Account.created_at.desc())
    rows, total = paginate(db, stmt, page, page_size)
    return Envelope(
        data=[AccountOut.model_validate(row) for row in rows],
        meta=Meta(page=page, page_size=page_size, total=total),
    )


@router.post("/accounts", response_model=Envelope[AccountOut])
def create_account(
    body: AccountIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("accounts.write"))],
) -> Envelope[AccountOut]:
    row = Account(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    db.flush()
    add_activity(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        entity_type="account",
        entity_id=str(row.id),
        activity_type="created",
        title="Account created",
    )
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="account.create",
        entity_type="account",
        entity_id=str(row.id),
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    emit_event(
        db,
        tenant_id=ctx.tenant_id,
        event_type="account.created",
        entity_type="account",
        entity_id=str(row.id),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=AccountOut.model_validate(row))


@router.get("/accounts/{account_id}", response_model=Envelope[AccountOut])
def get_account(
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("accounts.read"))],
) -> Envelope[AccountOut]:
    row = get_owned(db, Account, ctx.tenant_id, account_id)
    return Envelope(data=AccountOut.model_validate(row))


@router.get("/accounts/{account_id}/context", response_model=Envelope[AccountContextOut])
def get_account_context(
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("accounts.read"))],
) -> Envelope[AccountContextOut]:
    account = get_owned(db, Account, ctx.tenant_id, account_id)
    contacts = db.scalars(
        select(Contact).where(
            Contact.tenant_id == ctx.tenant_id,
            Contact.account_id == account_id,
            Contact.deleted_at.is_(None),
        )
    ).all()
    opps = db.scalars(
        select(Opportunity).where(
            Opportunity.tenant_id == ctx.tenant_id,
            Opportunity.account_id == account_id,
            Opportunity.deleted_at.is_(None),
        )
    ).all()
    tasks = db.scalars(
        select(Task).where(
            Task.tenant_id == ctx.tenant_id,
            Task.entity_type == "account",
            Task.entity_id == str(account_id),
            Task.deleted_at.is_(None),
        )
    ).all()
    return Envelope(
        data=AccountContextOut(
            account=AccountOut.model_validate(account),
            contacts=[ContactOut.model_validate(row) for row in contacts],
            opportunities=[OpportunityOut.model_validate(row) for row in opps],
            tasks=[TaskOut.model_validate(row) for row in tasks],
        )
    )


@router.patch("/accounts/{account_id}", response_model=Envelope[AccountOut])
def update_account(
    account_id: UUID,
    body: AccountIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("accounts.write"))],
) -> Envelope[AccountOut]:
    row = get_owned(db, Account, ctx.tenant_id, account_id)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_by = ctx.user.id
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="account.update",
        entity_type="account",
        entity_id=str(row.id),
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=AccountOut.model_validate(row))


@router.get("/contacts", response_model=Envelope[list[ContactOut]])
def list_contacts(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("contacts.read"))],
    page: int = 1,
    page_size: int = 25,
    q: str = "",
    account_id: UUID | None = None,
) -> Envelope[list[ContactOut]]:
    stmt = select(Contact).where(Contact.tenant_id == ctx.tenant_id, Contact.deleted_at.is_(None))
    if account_id:
        stmt = stmt.where(Contact.account_id == account_id)
    if q:
        stmt = stmt.where(
            or_(Contact.first_name.ilike(f"%{q}%"), Contact.last_name.ilike(f"%{q}%"), Contact.email.ilike(f"%{q}%"))
        )
    rows, total = paginate(db, stmt.order_by(Contact.created_at.desc()), page, page_size)
    account_ids = {row.account_id for row in rows if row.account_id}
    names: dict[UUID, str] = {}
    if account_ids:
        for account in db.scalars(
            select(Account).where(Account.tenant_id == ctx.tenant_id, Account.id.in_(account_ids))
        ):
            names[account.id] = account.name
    return Envelope(
        data=[_contact_out(db, ctx.tenant_id, row, names) for row in rows],
        meta=Meta(page=page, page_size=page_size, total=total),
    )


@router.post("/contacts", response_model=Envelope[ContactOut])
def create_contact(
    body: ContactIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("contacts.write"))],
) -> Envelope[ContactOut]:
    if body.account_id:
        get_owned(db, Account, ctx.tenant_id, body.account_id)
    row = Contact(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="contact.create",
        entity_type="contact",
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_contact_out(db, ctx.tenant_id, row))


@router.get("/contacts/{contact_id}", response_model=Envelope[ContactOut])
def get_contact(
    contact_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("contacts.read"))],
) -> Envelope[ContactOut]:
    return Envelope(data=_contact_out(db, ctx.tenant_id, get_owned(db, Contact, ctx.tenant_id, contact_id)))


@router.patch("/contacts/{contact_id}", response_model=Envelope[ContactOut])
def update_contact(
    contact_id: UUID,
    body: ContactIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("contacts.write"))],
) -> Envelope[ContactOut]:
    row = get_owned(db, Contact, ctx.tenant_id, contact_id)
    if body.account_id:
        get_owned(db, Account, ctx.tenant_id, body.account_id)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_by = ctx.user.id
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="contact.update",
        entity_type="contact",
        entity_id=str(row.id),
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_contact_out(db, ctx.tenant_id, row))


@router.get("/leads", response_model=Envelope[list[LeadOut]])
def list_leads(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("leads.read"))],
    page: int = 1,
    page_size: int = 25,
    q: str = "",
    status: str | None = None,
) -> Envelope[list[LeadOut]]:
    stmt = select(Lead).where(Lead.tenant_id == ctx.tenant_id, Lead.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Lead.status == status)
    if q:
        stmt = stmt.where(
            or_(Lead.first_name.ilike(f"%{q}%"), Lead.last_name.ilike(f"%{q}%"), Lead.company_name.ilike(f"%{q}%"))
        )
    rows, total = paginate(db, stmt.order_by(Lead.created_at.desc()), page, page_size)
    return Envelope(
        data=[_lead_out(db, row) for row in rows],
        meta=Meta(page=page, page_size=page_size, total=total),
    )


@router.post("/leads", response_model=Envelope[LeadOut])
def create_lead(
    body: LeadIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("leads.write"))],
) -> Envelope[LeadOut]:
    if body.source == "ai_discovery":
        raise HTTPException(status_code=422, detail="Discovered leads must come from /api/v1/discovery/run")
    if body.account_id:
        get_owned(db, Account, ctx.tenant_id, body.account_id)
    payload = body.model_dump()
    if payload.get("source") in {"", "manual"}:
        payload["source"] = "human"
    row = Lead(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **payload)
    db.add(row)
    db.flush()
    score_lead(db, row, emit=False, correlation_id=ctx.correlation_id)
    add_activity(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        entity_type="lead",
        entity_id=str(row.id),
        activity_type="created",
        title="Lead created",
    )
    emit_event(
        db,
        tenant_id=ctx.tenant_id,
        event_type="lead.created",
        entity_type="lead",
        entity_id=str(row.id),
        correlation_id=ctx.correlation_id,
    )
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="lead.create",
        entity_type="lead",
        entity_id=str(row.id),
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    process_pending_events(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, limit=200)
    db.commit()
    db.refresh(row)
    return Envelope(data=_lead_out(db, row))


@router.patch("/leads/{lead_id}", response_model=Envelope[LeadOut])
def update_lead(
    lead_id: UUID,
    body: LeadIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("leads.write"))],
) -> Envelope[LeadOut]:
    row = get_owned(db, Lead, ctx.tenant_id, lead_id)
    if body.account_id:
        get_owned(db, Account, ctx.tenant_id, body.account_id)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_by = ctx.user.id
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="lead.update",
        entity_type="lead",
        entity_id=str(row.id),
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_lead_out(db, row))


@router.get("/leads/{lead_id}", response_model=Envelope[LeadOut])
def get_lead(
    lead_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("leads.read"))],
) -> Envelope[LeadOut]:
    return Envelope(data=_lead_out(db, get_owned(db, Lead, ctx.tenant_id, lead_id)))


@router.post("/leads/{lead_id}/score", response_model=Envelope[LeadScoreOut])
def rescore_lead(
    lead_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("leads.score"))],
) -> Envelope[LeadScoreOut]:
    lead = get_owned(db, Lead, ctx.tenant_id, lead_id)
    score = score_lead(db, lead, correlation_id=ctx.correlation_id)
    process_pending_events(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    db.refresh(score)
    return Envelope(data=LeadScoreOut.model_validate(score))


@router.get("/opportunities", response_model=Envelope[list[OpportunityOut]])
def list_opportunities(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("opportunities.read"))],
    page: int = 1,
    page_size: int = 25,
    q: str = "",
    stage: str | None = None,
) -> Envelope[list[OpportunityOut]]:
    stmt = select(Opportunity).where(Opportunity.tenant_id == ctx.tenant_id, Opportunity.deleted_at.is_(None))
    if stage:
        stmt = stmt.where(Opportunity.stage == stage)
    if q:
        stmt = stmt.where(Opportunity.name.ilike(f"%{q}%"))
    rows, total = paginate(db, stmt.order_by(Opportunity.created_at.desc()), page, page_size)
    return Envelope(
        data=[OpportunityOut.model_validate(row) for row in rows],
        meta=Meta(page=page, page_size=page_size, total=total),
    )


@router.post("/opportunities", response_model=Envelope[OpportunityOut])
def create_opportunity(
    body: OpportunityIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("opportunities.write"))],
) -> Envelope[OpportunityOut]:
    get_owned(db, Account, ctx.tenant_id, body.account_id)
    payload = body.model_dump()
    payload["probability"] = STAGE_PROBABILITY.get(body.stage, body.probability)
    row = Opportunity(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **payload)
    db.add(row)
    db.flush()
    emit_event(
        db,
        tenant_id=ctx.tenant_id,
        event_type="opportunity.created",
        entity_type="opportunity",
        entity_id=str(row.id),
        correlation_id=ctx.correlation_id,
    )
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="opportunity.create",
        entity_type="opportunity",
        entity_id=str(row.id),
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=OpportunityOut.model_validate(row))


@router.get("/opportunities/{opportunity_id}", response_model=Envelope[OpportunityOut])
def get_opportunity(
    opportunity_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("opportunities.read"))],
) -> Envelope[OpportunityOut]:
    return Envelope(data=OpportunityOut.model_validate(get_owned(db, Opportunity, ctx.tenant_id, opportunity_id)))


@router.patch("/opportunities/{opportunity_id}", response_model=Envelope[OpportunityOut])
def update_opportunity(
    opportunity_id: UUID,
    body: OpportunityIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("opportunities.write"))],
) -> Envelope[OpportunityOut]:
    row = get_owned(db, Opportunity, ctx.tenant_id, opportunity_id)
    previous = row.stage
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.probability = STAGE_PROBABILITY.get(row.stage, row.probability)
    row.updated_by = ctx.user.id
    if previous != row.stage:
        emit_event(
            db,
            tenant_id=ctx.tenant_id,
            event_type="opportunity.stage_changed",
            entity_type="opportunity",
            entity_id=str(row.id),
            payload={"from": previous, "to": row.stage},
            correlation_id=ctx.correlation_id,
        )
    db.commit()
    db.refresh(row)
    return Envelope(data=OpportunityOut.model_validate(row))


@router.post("/opportunities/{opportunity_id}/close-won", response_model=Envelope[CustomerOut])
def close_opportunity_won(
    opportunity_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("opportunities.close"))],
) -> Envelope[CustomerOut]:
    _opp, customer, _renewal = close_won(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        opportunity_id=opportunity_id,
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(customer)
    return Envelope(data=CustomerOut.model_validate(customer))


@router.get("/tasks", response_model=Envelope[list[TaskOut]])
def list_tasks(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("tasks.read"))],
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    q: str = "",
) -> Envelope[list[TaskOut]]:
    stmt = select(Task).where(Task.tenant_id == ctx.tenant_id, Task.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Task.status == status)
    if q:
        stmt = stmt.where(or_(Task.title.ilike(f"%{q}%"), Task.description.ilike(f"%{q}%")))
    rows, total = paginate(db, stmt.order_by(Task.created_at.desc()), page, page_size)
    return Envelope(
        data=[TaskOut.model_validate(row) for row in rows],
        meta=Meta(page=page, page_size=page_size, total=total),
    )


@router.post("/tasks", response_model=Envelope[TaskOut])
def create_task(
    body: TaskIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("tasks.write"))],
) -> Envelope[TaskOut]:
    row = Task(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="task.create",
        entity_type="task",
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=TaskOut.model_validate(row))


@router.get("/tasks/{task_id}", response_model=Envelope[TaskOut])
def get_task(
    task_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("tasks.read"))],
) -> Envelope[TaskOut]:
    return Envelope(data=TaskOut.model_validate(get_owned(db, Task, ctx.tenant_id, task_id)))


@router.patch("/tasks/{task_id}", response_model=Envelope[TaskOut])
def update_task(
    task_id: UUID,
    body: TaskIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("tasks.write"))],
) -> Envelope[TaskOut]:
    row = get_owned(db, Task, ctx.tenant_id, task_id)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_by = ctx.user.id
    db.commit()
    db.refresh(row)
    return Envelope(data=TaskOut.model_validate(row))


@router.get("/activities", response_model=Envelope[list[ActivityOut]])
def list_activities(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("accounts.read"))],
    entity_type: str,
    entity_id: str,
) -> Envelope[list[ActivityOut]]:
    rows = db.scalars(
        select(Activity)
        .where(
            Activity.tenant_id == ctx.tenant_id,
            Activity.entity_type == entity_type,
            Activity.entity_id == entity_id,
            Activity.deleted_at.is_(None),
        )
        .order_by(Activity.created_at.desc())
    ).all()
    return Envelope(data=[ActivityOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.get("/icps", response_model=Envelope[list[ICPOut]])
def list_icps(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("icps.read"))],
) -> Envelope[list[ICPOut]]:
    rows = db.scalars(select(ICP).where(ICP.tenant_id == ctx.tenant_id, ICP.deleted_at.is_(None))).all()
    return Envelope(data=[ICPOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/icps", response_model=Envelope[ICPOut])
def create_icp(
    body: ICPIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("icps.write"))],
) -> Envelope[ICPOut]:
    row = ICP(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=ICPOut.model_validate(row))


@router.patch("/icps/{icp_id}", response_model=Envelope[ICPOut])
def update_icp(
    icp_id: UUID,
    body: ICPIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("icps.write"))],
) -> Envelope[ICPOut]:
    row = get_owned(db, ICP, ctx.tenant_id, icp_id)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_by = ctx.user.id
    db.commit()
    db.refresh(row)
    return Envelope(data=ICPOut.model_validate(row))


@router.get("/customers", response_model=Envelope[list[CustomerOut]])
def list_customers(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("accounts.read"))],
) -> Envelope[list[CustomerOut]]:
    rows = db.scalars(
        select(Customer).where(Customer.tenant_id == ctx.tenant_id, Customer.deleted_at.is_(None))
    ).all()
    out = []
    for row in rows:
        payload = CustomerOut.model_validate(row)
        account = db.scalar(select(Account).where(Account.id == row.account_id, Account.tenant_id == ctx.tenant_id))
        payload.account_name = account.name if account else None
        out.append(payload)
    return Envelope(data=out, meta=Meta(total=len(out)))


@router.post("/leads/{lead_id}/nba", response_model=Envelope[NBAOut])
def lead_nba(
    lead_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("leads.read"))],
) -> Envelope[NBAOut]:
    lead = get_owned(db, Lead, ctx.tenant_id, lead_id)
    row = generate_for_lead(db, ctx.tenant_id, lead, ctx.user.id)
    db.commit()
    db.refresh(row)
    return Envelope(data=NBAOut.model_validate(row))


@router.post("/opportunities/{opportunity_id}/nba", response_model=Envelope[NBAOut])
def opportunity_nba(
    opportunity_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("opportunities.read"))],
) -> Envelope[NBAOut]:
    opp = get_owned(db, Opportunity, ctx.tenant_id, opportunity_id)
    row = generate_for_opportunity(db, ctx.tenant_id, opp, ctx.user.id)
    db.commit()
    db.refresh(row)
    return Envelope(data=NBAOut.model_validate(row))

