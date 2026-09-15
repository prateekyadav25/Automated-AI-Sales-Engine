import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.models.autonomy import AutonomousRun, AutonomousRunStep
from app.schemas.autonomy import (
    AutonomyActivityOut,
    AutonomyPauseIn,
    AutonomyRetryIn,
    AutonomyRunIn,
    AutonomyRunOut,
    AutonomyStatusOut,
    AutonomyStepOut,
    AutopilotSettingsIn,
    AutopilotSettingsOut,
    EntityAutomationOut,
)
from app.schemas.common import Envelope, Meta
from app.services.audit import write_audit
from app.services.automation_state import pause_entity, resume_entity
from app.services.autonomy import run_autonomous_cycle
from app.services.autopilot_settings import apply_settings_update, get_or_create_settings
from app.services.autopilot_status import activity_feed, build_status, entity_trace
from app.services.journey_trace import full_trace
from app.services.orchestrator import retry_entity
from app.services.query import get_owned, paginate

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


def _run_out(db: Session, row: AutonomousRun) -> AutonomyRunOut:
    steps = db.scalars(
        select(AutonomousRunStep)
        .where(AutonomousRunStep.run_id == row.id, AutonomousRunStep.deleted_at.is_(None))
        .order_by(AutonomousRunStep.position.asc())
    ).all()
    payload = AutonomyRunOut.model_validate(row)
    payload.steps = [AutonomyStepOut.model_validate(step) for step in steps]
    return payload


@router.get("/settings", response_model=Envelope[AutopilotSettingsOut])
def get_settings(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> Envelope[AutopilotSettingsOut]:
    row = get_or_create_settings(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    db.refresh(row)
    return Envelope(data=AutopilotSettingsOut.model_validate(row))


@router.patch("/settings", response_model=Envelope[AutopilotSettingsOut])
def patch_settings(
    body: AutopilotSettingsIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.write"))],
) -> Envelope[AutopilotSettingsOut]:
    row = get_or_create_settings(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    apply_settings_update(db, row, body.model_dump(exclude_unset=True))
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="autonomy.settings",
        entity_type="autopilot_settings",
        entity_id=str(row.id),
        after=body.model_dump(exclude_unset=True),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=AutopilotSettingsOut.model_validate(row))


@router.get("/status", response_model=Envelope[AutonomyStatusOut])
def status(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> Envelope[AutonomyStatusOut]:
    return Envelope(data=build_status(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id))


@router.get("/activity", response_model=Envelope[list[AutonomyActivityOut]])
def activity(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=40, ge=1, le=100),
) -> Envelope[list[AutonomyActivityOut]]:
    rows = activity_feed(db, tenant_id=ctx.tenant_id, limit=500)
    start = (page - 1) * page_size
    window = rows[start : start + page_size]
    return Envelope(data=window, meta=Meta(page=page, page_size=page_size, total=len(rows)))


@router.get("/entities/{entity_type}/{entity_id}", response_model=Envelope[EntityAutomationOut])
def entity_automation(
    entity_type: str,
    entity_id: str,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> Envelope[EntityAutomationOut]:
    return Envelope(data=entity_trace(db, tenant_id=ctx.tenant_id, entity_type=entity_type, entity_id=entity_id))


@router.get("/entities/{entity_type}/{entity_id}/trace")
def entity_full_trace(
    entity_type: str,
    entity_id: str,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> Envelope[dict]:
    return Envelope(data=full_trace(db, tenant_id=ctx.tenant_id, entity_type=entity_type, entity_id=entity_id))


@router.post("/pause", response_model=Envelope[EntityAutomationOut])
def pause(
    body: AutonomyPauseIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.write"))],
) -> Envelope[EntityAutomationOut]:
    if body.scope == "tenant":
        settings = get_or_create_settings(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
        settings.enabled = False
        apply_settings_update(db, settings, {"enabled": False})
        db.commit()
        return Envelope(
            data=EntityAutomationOut(
                entity_type="tenant",
                entity_id=str(ctx.tenant_id),
                state="PAUSED",
                last_action="tenant_pause",
                next_action="",
                blocked_reason="Autopilot disabled",
                paused=True,
            )
        )
    if body.scope not in {"lead", "account", "opportunity", "customer"} or not body.entity_id:
        raise HTTPException(status_code=422, detail="scope must be tenant, lead, account, opportunity, or customer")
    row = pause_entity(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        entity_type=body.scope,
        entity_id=body.entity_id,
    )
    db.commit()
    return Envelope(data=entity_trace(db, tenant_id=ctx.tenant_id, entity_type=row.entity_type, entity_id=row.entity_id))


@router.post("/resume", response_model=Envelope[EntityAutomationOut])
def resume(
    body: AutonomyPauseIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.write"))],
) -> Envelope[EntityAutomationOut]:
    if body.scope == "tenant":
        settings = get_or_create_settings(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
        apply_settings_update(db, settings, {"enabled": True})
        db.commit()
        return Envelope(
            data=EntityAutomationOut(
                entity_type="tenant",
                entity_id=str(ctx.tenant_id),
                state="RUNNING",
                last_action="tenant_resume",
                next_action="reconcile",
                blocked_reason="",
                paused=False,
            )
        )
    if body.scope not in {"lead", "account", "opportunity", "customer"} or not body.entity_id:
        raise HTTPException(status_code=422, detail="scope must be tenant, lead, account, opportunity, or customer")
    row = resume_entity(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        entity_type=body.scope,
        entity_id=body.entity_id,
    )
    db.commit()
    return Envelope(data=entity_trace(db, tenant_id=ctx.tenant_id, entity_type=row.entity_type, entity_id=row.entity_id))


@router.post("/retry", response_model=Envelope[dict])
def retry(
    body: AutonomyRetryIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.write"))],
) -> Envelope[dict]:
    count = retry_entity(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
    )
    db.commit()
    return Envelope(data={"processed": count})


@router.get("/runs", response_model=Envelope[list[AutonomyRunOut]])
def list_runs(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> Envelope[list[AutonomyRunOut]]:
    stmt = (
        select(AutonomousRun)
        .where(AutonomousRun.tenant_id == ctx.tenant_id, AutonomousRun.deleted_at.is_(None))
        .order_by(AutonomousRun.created_at.desc())
    )
    rows, total = paginate(db, stmt, page, page_size)
    return Envelope(data=[_run_out(db, row) for row in rows], meta=Meta(page=page, page_size=page_size, total=total))


@router.get("/events")
async def autonomy_events(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> StreamingResponse:
    async def stream():
        last = ""
        while not await request.is_disconnected():
            status = build_status(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
            payload = status.model_dump(mode="json")
            encoded = json.dumps({"type": "status", "data": payload}, default=str)
            if encoded != last:
                yield f"data: {encoded}\n\n"
                last = encoded
            else:
                yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/runs", response_model=Envelope[AutonomyRunOut])
def start_run(
    body: AutonomyRunIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.write"))],
) -> Envelope[AutonomyRunOut]:
    enforce_rate_limit(key=f"run:{ctx.tenant_id}", limit=20, window_seconds=60)
    row = run_autonomous_cycle(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        trigger="manual",
        correlation_id=ctx.correlation_id,
        profile_urls=body.profile_urls,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_run_out(db, row))


@router.get("/runs/{run_id}", response_model=Envelope[AutonomyRunOut])
def get_run(
    run_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
) -> Envelope[AutonomyRunOut]:
    return Envelope(data=_run_out(db, get_owned(db, AutonomousRun, ctx.tenant_id, run_id)))
