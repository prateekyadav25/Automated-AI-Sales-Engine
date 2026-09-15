import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.pilot import ManualOverride, OperatorBrief, WhatsAppTemplate
from app.schemas.common import Envelope, Meta
from app.schemas.pilot import (
    BriefOut,
    OverrideIn,
    PilotActivateIn,
    PilotActivateOut,
    PilotCheckOut,
    PilotReadinessOut,
    WhatsAppTemplateIn,
    WhatsAppTemplateOut,
)
from app.services.audit import write_audit
from app.services.data_quality import learning_progress, refresh_quality
from app.services.operator_briefs import generate_brief
from app.services.pilot_readiness import PilotActivationError, activate_mode, evaluate_readiness, export_config
from app.services.roi import ai_prepared_pipeline, automation_metrics, campaign_attribution, touches_report, usage_costs

router = APIRouter(prefix="/pilot", tags=["pilot"])


@router.get("/readiness", response_model=Envelope[PilotReadinessOut])
def get_readiness(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.view"))],
) -> Envelope[PilotReadinessOut]:
    report = evaluate_readiness(db, tenant_id=ctx.tenant_id)
    db.commit()
    return Envelope(
        data=PilotReadinessOut(
            operating_mode=report["operating_mode"],
            environment=report["environment"],
            can_activate_pilot=report["can_activate_pilot"],
            can_activate_production=report["can_activate_production"],
            blockers=report["blockers"],
            items=[PilotCheckOut(**item) for item in report["items"]],
        )
    )


@router.post("/activate", response_model=Envelope[PilotActivateOut])
def activate(
    body: PilotActivateIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.activate"))],
) -> Envelope[PilotActivateOut]:
    try:
        tenant = activate_mode(
            db,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user.id,
            target=body.target,
            reason=body.reason,
        )
    except PilotActivationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return Envelope(data=PilotActivateOut(operating_mode=tenant.operating_mode))


@router.get("/config-export")
def config_export(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.view"))],
) -> Envelope[dict]:
    payload = export_config(db, tenant_id=ctx.tenant_id)
    return Envelope(data=payload)


@router.get("/quality")
def quality(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.view"))],
) -> Envelope[dict]:
    issues = refresh_quality(db, tenant_id=ctx.tenant_id)
    progress = learning_progress(db, tenant_id=ctx.tenant_id)
    db.commit()
    return Envelope(data={"issues": issues, "learning": progress}, meta=Meta(total=len(issues)))


@router.get("/roi")
def roi(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.view"))],
) -> Envelope[dict]:
    return Envelope(
        data={
            "automation": automation_metrics(db, tenant_id=ctx.tenant_id),
            "touches": touches_report(db, tenant_id=ctx.tenant_id),
            "pipeline": ai_prepared_pipeline(db, tenant_id=ctx.tenant_id),
            "costs": usage_costs(db, tenant_id=ctx.tenant_id),
            "campaigns": campaign_attribution(db, tenant_id=ctx.tenant_id),
        }
    )


@router.get("/costs")
def costs(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.view"))],
) -> Envelope[dict]:
    return Envelope(data=usage_costs(db, tenant_id=ctx.tenant_id))


@router.post("/briefs/{kind}", response_model=Envelope[BriefOut])
def create_brief(
    kind: str,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.view"))],
) -> Envelope[BriefOut]:
    if kind not in {"daily", "weekly"}:
        raise HTTPException(status_code=422, detail="kind must be daily or weekly")
    row = generate_brief(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, kind=kind)
    db.commit()
    db.refresh(row)
    return Envelope(
        data=BriefOut(
            id=row.id,
            kind=row.kind,
            payload=json.loads(row.payload_json or "{}"),
            period_start=row.period_start,
            period_end=row.period_end,
        )
    )


@router.get("/briefs", response_model=Envelope[list[BriefOut]])
def list_briefs(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.view"))],
) -> Envelope[list[BriefOut]]:
    rows = db.scalars(
        select(OperatorBrief)
        .where(OperatorBrief.tenant_id == ctx.tenant_id, OperatorBrief.deleted_at.is_(None))
        .order_by(OperatorBrief.created_at.desc())
    ).all()
    return Envelope(
        data=[
            BriefOut(
                id=row.id,
                kind=row.kind,
                payload=json.loads(row.payload_json or "{}"),
                period_start=row.period_start,
                period_end=row.period_end,
            )
            for row in rows
        ],
        meta=Meta(total=len(rows)),
    )


@router.post("/overrides")
def create_override(
    body: OverrideIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("pilot.activate"))],
) -> Envelope[dict]:
    row = ManualOverride(
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        field_name=body.field_name,
        previous_json=json.dumps(body.previous, default=str),
        new_json=json.dumps(body.new, default=str),
        reason=body.reason,
    )
    db.add(row)
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="pilot.override",
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        before=body.previous,
        after=body.new,
    )
    db.commit()
    return Envelope(data={"id": str(row.id)})


@router.post("/whatsapp/templates", response_model=Envelope[WhatsAppTemplateOut])
def upsert_template(
    body: WhatsAppTemplateIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
) -> Envelope[WhatsAppTemplateOut]:
    row = db.scalar(
        select(WhatsAppTemplate).where(
            WhatsAppTemplate.tenant_id == ctx.tenant_id,
            WhatsAppTemplate.template_id == body.template_id,
            WhatsAppTemplate.language == body.language,
            WhatsAppTemplate.deleted_at.is_(None),
        )
    )
    if row is None:
        row = WhatsAppTemplate(
            tenant_id=ctx.tenant_id,
            created_by=ctx.user.id,
            template_id=body.template_id,
            language=body.language,
        )
        db.add(row)
    row.status = body.status
    row.body = body.body
    row.variables_json = json.dumps(body.variables)
    db.commit()
    db.refresh(row)
    return Envelope(data=WhatsAppTemplateOut.model_validate(row))


@router.get("/whatsapp/templates", response_model=Envelope[list[WhatsAppTemplateOut]])
def list_templates(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.read"))],
) -> Envelope[list[WhatsAppTemplateOut]]:
    rows = db.scalars(
        select(WhatsAppTemplate).where(WhatsAppTemplate.tenant_id == ctx.tenant_id, WhatsAppTemplate.deleted_at.is_(None))
    ).all()
    return Envelope(data=[WhatsAppTemplateOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))
