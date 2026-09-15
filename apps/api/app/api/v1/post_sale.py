from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.crm import Customer
from app.models.lifecycle import Referral
from app.models.post_sale import ExpansionRecommendation
from app.schemas.common import Envelope, Meta
from app.schemas.ml import FeedbackIn
from app.schemas.pilot import ExpansionOutcomeIn, UsefulIn
from app.schemas.post_sale import Customer360Out, ExpansionRecOut, LifecycleLaneOut, PostSaleAttentionOut
from app.services.advocacy import ingest_referral
from app.services.customer_360 import build_customer_360
from app.services.outcomes import record_expansion_outcome
from app.services.post_sale_reconcile import attention, lifecycle_lanes
from app.services.query import get_owned

router = APIRouter(prefix="/post-sale", tags=["post-sale"])


@router.get("/attention", response_model=Envelope[PostSaleAttentionOut])
def post_sale_attention(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.read"))],
) -> Envelope[PostSaleAttentionOut]:
    return Envelope(data=attention(db, ctx.tenant_id))


@router.get("/expansion", response_model=Envelope[list[ExpansionRecOut]])
def list_expansion_recs(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.read"))],
) -> Envelope[list[ExpansionRecOut]]:
    rows = db.scalars(
        select(ExpansionRecommendation).where(
            ExpansionRecommendation.tenant_id == ctx.tenant_id,
            ExpansionRecommendation.deleted_at.is_(None),
        )
    ).all()
    return Envelope(data=[ExpansionRecOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/expansion/{recommendation_id}/feedback", response_model=Envelope[dict])
def expansion_feedback(
    recommendation_id: UUID,
    body: FeedbackIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.write"))],
) -> Envelope[dict]:
    rec = get_owned(db, ExpansionRecommendation, ctx.tenant_id, recommendation_id)
    from app.services.ml.history import record_feedback

    row = record_feedback(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        recommendation_id=rec.id,
        action=body.action,
        entity_id=str(rec.customer_id),
        note=body.note,
        useful=body.useful,
    )
    db.commit()
    return Envelope(data={"id": str(row.id), "action": row.action, "useful": row.useful, "ground_truth": False})


@router.post("/expansion/{recommendation_id}/outcome", response_model=Envelope[ExpansionRecOut])
def expansion_outcome(
    recommendation_id: UUID,
    body: ExpansionOutcomeIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.write"))],
) -> Envelope[ExpansionRecOut]:
    rec = record_expansion_outcome(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        recommendation_id=recommendation_id,
        status=body.status,
        value=Decimal(str(body.value)) if body.value is not None else None,
        product=body.product,
    )
    db.commit()
    db.refresh(rec)
    return Envelope(data=ExpansionRecOut.model_validate(rec))


@router.post("/expansion/{recommendation_id}/useful", response_model=Envelope[dict])
def expansion_useful(
    recommendation_id: UUID,
    body: UsefulIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.write"))],
) -> Envelope[dict]:
    rec = get_owned(db, ExpansionRecommendation, ctx.tenant_id, recommendation_id)
    from app.services.ml.history import record_feedback

    row = record_feedback(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        recommendation_id=rec.id,
        action="edited",
        entity_id=str(rec.customer_id),
        note="useful",
        useful=body.useful,
    )
    db.commit()
    return Envelope(data={"id": str(row.id), "useful": row.useful, "ground_truth": False})


@router.get("/lanes", response_model=Envelope[list[LifecycleLaneOut]])
def post_sale_lanes(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> Envelope[list[LifecycleLaneOut]]:
    rows = lifecycle_lanes(db, ctx.tenant_id)
    return Envelope(data=rows, meta=Meta(total=len(rows)))


@router.get("/customers/{customer_id}", response_model=Envelope[Customer360Out])
def customer_360(
    customer_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.read"))],
) -> Envelope[Customer360Out]:
    customer = get_owned(db, Customer, ctx.tenant_id, customer_id)
    return Envelope(data=build_customer_360(db, tenant_id=ctx.tenant_id, customer=customer))


@router.post("/referrals/{referral_id}/ingest", response_model=Envelope[dict])
def ingest(
    referral_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("advocacy.write"))],
) -> Envelope[dict]:
    referral = get_owned(db, Referral, ctx.tenant_id, referral_id)
    lead = ingest_referral(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, referral=referral)
    db.commit()
    return Envelope(data={"lead_id": str(lead.id) if lead else None, "consent_email": False})
