from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.crm import ActivityOut, KPIOut, OpportunityOut, StageMixOut, TaskOut
from app.services.command_center import (
    at_risk_opportunities,
    kpis,
    overdue_tasks,
    pipeline_mix,
    recent_activities,
)
from app.services.lifecycle import lifecycle_pulse

router = APIRouter(prefix="/command-center", tags=["command-center"])


@router.get("/kpis", response_model=Envelope[KPIOut])
def get_kpis(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("command_center.read"))],
) -> Envelope[KPIOut]:
    return Envelope(data=kpis(db, ctx.tenant_id))


@router.get("/overview")
def get_overview(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("command_center.read"))],
) -> Envelope[dict]:
    return Envelope(
        data={
            "kpis": kpis(db, ctx.tenant_id).model_dump(mode="json"),
            "pipeline_by_stage": [row.model_dump(mode="json") for row in pipeline_mix(db, ctx.tenant_id)],
            "recent_activities": [row.model_dump(mode="json") for row in recent_activities(db, ctx.tenant_id)],
            "overdue_tasks": [row.model_dump(mode="json") for row in overdue_tasks(db, ctx.tenant_id)],
            "at_risk_opportunities": [
                row.model_dump(mode="json") for row in at_risk_opportunities(db, ctx.tenant_id)
            ],
            "lifecycle": lifecycle_pulse(db, ctx.tenant_id),
        }
    )


@router.get("/pipeline-mix", response_model=Envelope[list[StageMixOut]])
def get_pipeline_mix(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("command_center.read"))],
) -> Envelope[list[StageMixOut]]:
    return Envelope(data=pipeline_mix(db, ctx.tenant_id))


@router.get("/activity", response_model=Envelope[list[ActivityOut]])
def get_activity(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("command_center.read"))],
) -> Envelope[list[ActivityOut]]:
    return Envelope(data=recent_activities(db, ctx.tenant_id))


@router.get("/work-queue")
def get_work_queue(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("command_center.read"))],
) -> Envelope[dict[str, list[TaskOut] | list[OpportunityOut]]]:
    return Envelope(
        data={
            "overdue_tasks": overdue_tasks(db, ctx.tenant_id),
            "at_risk_opportunities": at_risk_opportunities(db, ctx.tenant_id),
        }
    )
