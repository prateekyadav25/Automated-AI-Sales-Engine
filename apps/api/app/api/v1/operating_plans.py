from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.schemas.common import Envelope
from app.services.content_calendar import attach_local_preview, promote_proposal, propose_calendar
from app.services.discovery import bound_operating_plan
from app.services.marketing import (
    attributed_outcomes,
    authorize_version,
    generate_draft,
    preview_schedule,
    publication_evidence,
    publish_scheduled,
    record_metrics,
    research_prospects,
    resume_plan,
    review_versions,
    revise_version,
    schedule_version,
    start_operating_plan,
)
from app.services.operations import channel_readiness
from app.services.organic_metrics import collect_linkedin_metrics, prepare_recommendation

router = APIRouter(prefix="/operating-plans", tags=["operating-plans"])


class VersionIn(BaseModel):
    version_id: UUID
    body: str = ""


class MetricsIn(BaseModel):
    version_id: UUID
    impressions: int | None = None
    clicks: int | None = None
    spend: str | None = None


class CalendarIn(BaseModel):
    plan_id: UUID | None = None
    objective: str = ""
    audience: str = ""
    channels: list[str] = []
    start_on: str = ""
    end_on: str = ""
    cadence_days: int = 1
    themes: list[str] = []
    call_to_action: str = ""


class ProposalIn(BaseModel):
    proposal_id: UUID


@router.get("/readiness")
def readiness(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
    channel: str = "email",
) -> Envelope[dict]:
    return Envelope(data=channel_readiness(db, tenant_id=ctx.tenant_id, channel=channel))


@router.post("/start")
def start_plan(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
    channel: str = "linkedin",
    product_id: UUID | None = None,
) -> Envelope[dict]:
    data = start_operating_plan(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        channel=channel,
        product_id=product_id,
    )
    db.commit()
    return Envelope(data=data)


@router.post("/research")
def research(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
    plan_id: UUID | None = None,
    icp_id: UUID | None = None,
) -> Envelope[dict]:
    data = research_prospects(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, plan_id=plan_id, icp_id=icp_id)
    db.commit()
    return Envelope(data=data)


@router.post("/drafts")
def drafts(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    data = generate_draft(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data=data)


@router.get("/review")
def review(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
) -> Envelope[dict]:
    return Envelope(data=review_versions(db, ctx.tenant_id))


@router.post("/authorize")
def authorize(
    body: VersionIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    data = authorize_version(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, version_id=body.version_id)
    db.commit()
    return Envelope(data=data)


@router.post("/revise")
def revise(
    body: VersionIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    data = revise_version(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, version_id=body.version_id, body=body.body)
    db.commit()
    return Envelope(data=data)


@router.get("/schedule")
def schedule_preview(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
) -> Envelope[dict]:
    return Envelope(data=preview_schedule(db, ctx.tenant_id))


@router.post("/schedule")
def schedule(
    body: VersionIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    data = schedule_version(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, version_id=body.version_id)
    db.commit()
    return Envelope(data=data)


@router.post("/publish")
def publish(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    data = publish_scheduled(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data=data)


@router.get("/evidence")
def evidence(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
) -> Envelope[dict]:
    return Envelope(data=publication_evidence(db, ctx.tenant_id))


@router.get("/outcomes")
def outcomes(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
) -> Envelope[dict]:
    return Envelope(data=attributed_outcomes(db, ctx.tenant_id))


@router.post("/metrics")
def metrics(
    body: MetricsIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    supplied = {key: getattr(body, key) for key in body.model_fields_set if key != "version_id" and getattr(body, key) is not None}
    data = record_metrics(db, tenant_id=ctx.tenant_id, version_id=body.version_id, metrics=supplied or None)
    db.commit()
    return Envelope(data=data)


@router.post("/calendar")
def calendar(
    body: CalendarIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    data = propose_calendar(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        plan_id=body.plan_id,
        objective=body.objective,
        audience=body.audience,
        channels=body.channels,
        start_on=body.start_on,
        end_on=body.end_on,
        cadence_days=body.cadence_days,
        themes=body.themes,
        call_to_action=body.call_to_action,
    )
    db.commit()
    return Envelope(data=data)


@router.post("/proposals/{proposal_id}/preview")
async def preview(
    proposal_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
    file: Annotated[UploadFile, File()],
) -> Envelope[dict]:
    data = attach_local_preview(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        proposal_id=proposal_id,
        data=await file.read(),
    )
    db.commit()
    return Envelope(data=data)


@router.post("/proposals/promote")
def promote(
    body: ProposalIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    data = promote_proposal(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, proposal_id=body.proposal_id)
    db.commit()
    return Envelope(data=data)


@router.post("/metrics/collect")
def collect_metrics(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    """Record a blocked or client-less read. This route does not open a live provider client."""
    data = collect_linkedin_metrics(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, client=None)
    plan, _message = bound_operating_plan(db, ctx.tenant_id, None)
    if plan is not None and not data.get("blocked"):
        data["recommendation"] = prepare_recommendation(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, plan=plan)
    db.commit()
    return Envelope(data=data)


@router.post("/resume")
def resume(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[dict]:
    data = resume_plan(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data=data)
