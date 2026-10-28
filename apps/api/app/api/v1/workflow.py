"""Governed revenue workflow: decisions, launch, grants, and commercial evidence."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.crm import Lead, Opportunity
from app.models.execution import AuthorizationGrant, StageEvidence, UserInvitation
from app.models.identity import DomainEvent
from app.models.lifecycle import MeetingRecord, Quote, Sequence
from app.schemas.common import Envelope, Meta
from app.services.autopilot_settings import get_or_create_settings
from app.services.commercial_close import CommercialCloseError, record_acceptance, review_acceptance
from app.services.crm import STAGE_PROBABILITY
from app.services.event_delivery import replay_event
from app.services.journey_engine import record_sales_qualification, sequence_is_runnable, stage_block_reason
from app.services.query import get_owned
from app.services.revenue_ledger import retention_metrics
from app.services.workflow_surface import (
    accept_invitation,
    command_queue,
    create_campaign_plan,
    create_objective,
    deactivate_user,
    invite_user,
    launch_checklist,
    operating_snapshot,
    record_evidence,
)

router = APIRouter(prefix="/workflow", tags=["workflow"])


class GrantIn(BaseModel):
    name: str
    mode: str = "assisted"
    workflow: str = "inbound"
    channel: str = "email"
    segment: str = ""
    volume_cap: int = 0
    cost_cap: Decimal = Decimal("0")


class ObjectiveIn(BaseModel):
    name: str
    segment: str = ""
    period: str = ""
    target_measure: str = "qualified_pipeline"
    target_amount: Decimal = Decimal("0")
    offer_key: str = ""
    status: str = "active"


class CampaignPlanIn(BaseModel):
    name: str
    channel: str
    budget: Decimal
    audience: str = ""
    offer_key: str = ""
    product_id: UUID | None = None
    objective_id: UUID | None = None
    status: str = "approved"
    currency: str = "INR"


class MeetingOutcomeIn(BaseModel):
    qualified: bool
    summary: str = ""


class StageAdvanceIn(BaseModel):
    stage: str
    evidence: str = ""


class QuoteAcceptIn(BaseModel):
    note: str = ""
    contact_id: UUID | None = None
    relationship: str = ""
    source: str = "manual"
    evidence: str = ""


class AcceptanceReviewIn(BaseModel):
    note: str = ""


class InviteIn(BaseModel):
    email: str
    role_name: str = "Sales Rep"
    name: str = ""
    password: str = ""


class AcceptIn(BaseModel):
    name: str
    password: str
    token: str


class EvidenceIn(BaseModel):
    kind: str
    status: str = "passed"
    detail: str = ""


@router.get("/command", response_model=Envelope[list[dict]])
def command(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("command_center.read"))],
) -> Envelope[list[dict]]:
    rows = command_queue(db, ctx.tenant_id)
    return Envelope(data=rows, meta=Meta(total=len(rows)))


@router.get("/launch", response_model=Envelope[dict])
def launch(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> Envelope[dict]:
    return Envelope(data=launch_checklist(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id))


@router.post("/grants", response_model=Envelope[dict])
def create_grant(
    body: GrantIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> Envelope[dict]:
    if body.mode not in {"observe", "assisted", "bounded_autopilot"}:
        raise HTTPException(status_code=422, detail="Mode must be observe, assisted, or bounded_autopilot.")
    row = AuthorizationGrant(
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        name=body.name,
        mode=body.mode,
        workflow=body.workflow,
        channel=body.channel,
        segment=body.segment,
        volume_cap=body.volume_cap,
        cost_cap=body.cost_cap,
        status="active",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data={"id": str(row.id), "mode": row.mode, "workflow": row.workflow, "channel": row.channel})


@router.post("/objectives", response_model=Envelope[dict])
def post_objective(
    body: ObjectiveIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    row = create_objective(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, payload=body.model_dump())
    db.commit()
    return Envelope(data={"id": str(row.id), "name": row.name, "status": row.status})


@router.post("/campaign-plans", response_model=Envelope[dict])
def post_campaign_plan(
    body: CampaignPlanIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    if body.budget <= 0:
        raise HTTPException(status_code=422, detail="Campaign budget must be approved and greater than zero.")
    row = create_campaign_plan(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, payload=body.model_dump())
    db.commit()
    return Envelope(data={"id": str(row.id), "budget": str(row.budget), "status": row.status, "channel": row.channel})


@router.post("/events/{event_id}/replay", response_model=Envelope[dict])
def replay(
    event_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> Envelope[dict]:
    event = db.get(DomainEvent, event_id)
    if event is None or event.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="Event was not found.")
    message = replay_event(db, event, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data={"status": event.delivery_status, "message": message})


@router.post("/meetings/{meeting_id}/outcome", response_model=Envelope[dict])
def meeting_outcome(
    meeting_id: UUID,
    body: MeetingOutcomeIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("opportunities.write"))],
) -> Envelope[dict]:
    meeting = get_owned(db, MeetingRecord, ctx.tenant_id, meeting_id)
    if meeting.lead_id is None:
        raise HTTPException(status_code=409, detail="Meeting has no lead to qualify.")
    lead = get_owned(db, Lead, ctx.tenant_id, meeting.lead_id)
    opportunity = record_sales_qualification(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        lead=lead,
        meeting=meeting,
        qualified=body.qualified,
        summary=body.summary,
    )
    db.commit()
    return Envelope(data={"qualified": body.qualified, "opportunity_id": str(opportunity.id) if opportunity else None})


@router.post("/opportunities/{opportunity_id}/advance", response_model=Envelope[dict])
def advance_stage(
    opportunity_id: UUID,
    body: StageAdvanceIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("opportunities.write"))],
) -> Envelope[dict]:
    opportunity = get_owned(db, Opportunity, ctx.tenant_id, opportunity_id)
    if body.stage == "closed_won":
        raise HTTPException(status_code=409, detail="Close-won is a separate decision and needs an accepted quote.")
    reason = stage_block_reason(db, tenant_id=ctx.tenant_id, opportunity=opportunity, target=body.stage)
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    if body.evidence:
        db.add(
            StageEvidence(
                tenant_id=ctx.tenant_id,
                created_by=ctx.user.id,
                entity_type="opportunity",
                entity_id=str(opportunity.id),
                stage=body.stage,
                kind="stage_note",
                summary=body.evidence,
                source="human",
            )
        )
    opportunity.stage = body.stage
    opportunity.probability = STAGE_PROBABILITY.get(body.stage, opportunity.probability)
    db.commit()
    return Envelope(data={"id": str(opportunity.id), "stage": opportunity.stage})


@router.post("/quotes/{quote_id}/accept", response_model=Envelope[dict])
def accept_quote(
    quote_id: UUID,
    body: QuoteAcceptIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("commercial.write"))],
) -> Envelope[dict]:
    quote = get_owned(db, Quote, ctx.tenant_id, quote_id)
    try:
        acceptance = record_acceptance(
            db,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user.id,
            quote=quote,
            contact_id=body.contact_id,
            relationship=body.relationship,
            source=body.source,
            evidence=body.evidence or body.note,
        )
    except CommercialCloseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    db.commit()
    return Envelope(
        data={
            "id": str(quote.id),
            "status": quote.status,
            "version": quote.version,
            "acceptance_id": str(acceptance.id),
            "review_state": acceptance.review_state,
            "source": acceptance.source,
            "customer_created": False,
        }
    )


@router.post("/quotes/{quote_id}/acceptance/review", response_model=Envelope[dict])
def review_quote_acceptance(
    quote_id: UUID,
    body: AcceptanceReviewIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("commercial.write"))],
) -> Envelope[dict]:
    quote = get_owned(db, Quote, ctx.tenant_id, quote_id)
    try:
        acceptance = review_acceptance(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, quote=quote, note=body.note)
    except CommercialCloseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    db.commit()
    return Envelope(data={"id": str(quote.id), "review_state": acceptance.review_state, "provider_verified": False})


@router.post("/sequences/{sequence_id}/activate", response_model=Envelope[dict])
def activate_sequence(
    sequence_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("sequences.write"))],
) -> Envelope[dict]:
    sequence = get_owned(db, Sequence, ctx.tenant_id, sequence_id)
    sequence.status = "live"
    if not sequence_is_runnable(db, sequence):
        sequence.status = "draft"
        db.commit()
        raise HTTPException(status_code=409, detail="Sequence has an unsupported step. Activation refused.")
    db.commit()
    return Envelope(data={"id": str(sequence.id), "status": sequence.status, "version": sequence.version})


@router.get("/retention", response_model=Envelope[dict])
def retention(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("forecast.read"))],
) -> Envelope[dict]:
    return Envelope(data=retention_metrics(db, ctx.tenant_id))


@router.get("/operations", response_model=Envelope[dict])
def operations(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.view"))],
) -> Envelope[dict]:
    settings = get_or_create_settings(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    return Envelope(data=operating_snapshot(db, tenant_id=ctx.tenant_id, settings=settings))


@router.post("/operations/evidence", response_model=Envelope[dict])
def evidence(
    body: EvidenceIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.activate"))],
) -> Envelope[dict]:
    row = record_evidence(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, kind=body.kind, status=body.status, detail=body.detail)
    db.commit()
    return Envelope(data={"id": str(row.id), "kind": row.kind, "status": row.status})


@router.post("/invitations", response_model=Envelope[dict])
def invitation(
    body: InviteIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("users.write"))],
) -> Envelope[dict]:
    if body.password:
        raise HTTPException(status_code=422, detail="Create the invitation first. The password is set when it is accepted.")
    row, token = invite_user(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, email=body.email, role_name=body.role_name)
    db.commit()
    return Envelope(data={"id": str(row.id), "email": row.email, "status": row.status, "token": token})


@router.post("/invitations/{invitation_id}/accept", response_model=Envelope[dict])
def accept(
    invitation_id: UUID,
    body: AcceptIn,
    db: Annotated[Session, Depends(get_db)],
) -> Envelope[dict]:
    invitation = db.get(UserInvitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation was not found.")
    try:
        user = accept_invitation(
            db,
            tenant_id=invitation.tenant_id,
            invitation_id=invitation_id,
            name=body.name,
            password=body.password,
            token=body.token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return Envelope(data={"id": str(user.id), "email": user.email, "is_active": user.is_active})


@router.post("/users/{user_id}/deactivate", response_model=Envelope[dict])
def deactivate(
    user_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("users.write"))],
) -> Envelope[dict]:
    try:
        user = deactivate_user(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return Envelope(data={"id": str(user.id), "is_active": user.is_active})
