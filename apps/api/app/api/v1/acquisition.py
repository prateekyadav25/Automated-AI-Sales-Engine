from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.acquisition import DedupeReview, InboundCapture
from app.schemas.acquisition import (
    AcquisitionOverview,
    CaptureIn,
    CaptureOut,
    CaptureResult,
    DedupeDecision,
    DedupeOut,
)
from app.schemas.common import Envelope, Meta
from app.schemas.crm import LeadOut, LeadScoreOut
from app.services.acquisition import capture_inbound, decide_dedupe
from app.services.audit import write_audit
from app.services.crm import latest_lead_score
from app.services.orchestrator import process_pending_events
from app.services.query import get_owned, paginate

router = APIRouter(prefix="/acquisition", tags=["acquisition"])


def _lead_out(db: Session, lead) -> LeadOut:
    payload = LeadOut.model_validate(lead)
    score = latest_lead_score(db, lead)
    if score is not None:
        payload.latest_score = LeadScoreOut.model_validate(score)
    return payload


@router.get("/overview", response_model=Envelope[AcquisitionOverview])
def overview(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("acquisition.read"))],
) -> Envelope[AcquisitionOverview]:
    captures = db.scalar(select(func.count()).where(InboundCapture.tenant_id == ctx.tenant_id, InboundCapture.deleted_at.is_(None))) or 0
    accepted = db.scalar(select(func.count()).where(InboundCapture.tenant_id == ctx.tenant_id, InboundCapture.status == "accepted")) or 0
    duplicates = db.scalar(select(func.count()).where(InboundCapture.tenant_id == ctx.tenant_id, InboundCapture.status == "duplicate_review")) or 0
    pending = db.scalar(select(func.count()).where(DedupeReview.tenant_id == ctx.tenant_id, DedupeReview.status == "pending")) or 0
    return Envelope(
        data=AcquisitionOverview(
            captures=int(captures),
            accepted=int(accepted),
            duplicate_review=int(duplicates),
            pending_dedupe=int(pending),
        )
    )


@router.post("/capture", response_model=Envelope[CaptureResult])
def capture(
    body: CaptureIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("acquisition.capture"))],
) -> Envelope[CaptureResult]:
    capture_row, lead, reviews = capture_inbound(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        payload=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="acquisition.capture",
        entity_type="inbound_capture",
        entity_id=str(capture_row.id),
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    process_pending_events(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    db.refresh(capture_row)
    if lead is not None:
        db.refresh(lead)
    return Envelope(
        data=CaptureResult(
            capture=CaptureOut.model_validate(capture_row),
            lead=_lead_out(db, lead) if lead is not None else None,
            reviews_opened=len(reviews),
        )
    )


@router.get("/captures", response_model=Envelope[list[CaptureOut]])
def list_captures(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("acquisition.read"))],
    page: int = 1,
    page_size: int = 25,
) -> Envelope[list[CaptureOut]]:
    stmt = select(InboundCapture).where(InboundCapture.tenant_id == ctx.tenant_id, InboundCapture.deleted_at.is_(None)).order_by(InboundCapture.created_at.desc())
    rows, total = paginate(db, stmt, page, page_size)
    return Envelope(data=[CaptureOut.model_validate(row) for row in rows], meta=Meta(page=page, page_size=page_size, total=total))


@router.get("/dedupe", response_model=Envelope[list[DedupeOut]])
def list_dedupe(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("acquisition.read"))],
    status: str = "pending",
) -> Envelope[list[DedupeOut]]:
    stmt = select(DedupeReview).where(DedupeReview.tenant_id == ctx.tenant_id, DedupeReview.deleted_at.is_(None))
    if status:
        stmt = stmt.where(DedupeReview.status == status)
    rows = db.scalars(stmt.order_by(DedupeReview.created_at.desc())).all()
    return Envelope(data=[DedupeOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/dedupe/{review_id}/decide", response_model=Envelope[DedupeOut])
def decide(
    review_id: UUID,
    body: DedupeDecision,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("acquisition.write"))],
) -> Envelope[DedupeOut]:
    row = get_owned(db, DedupeReview, ctx.tenant_id, review_id)
    decide_dedupe(db, row, body.decision)
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="acquisition.dedupe",
        entity_type="dedupe_review",
        entity_id=str(row.id),
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=DedupeOut.model_validate(row))
