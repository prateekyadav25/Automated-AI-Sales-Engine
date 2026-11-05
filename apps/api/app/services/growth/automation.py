"""Worker entry points for one tenant. The beat runs them through run_per_tenant.

Planning and creation run only when ENABLE_SOCIAL_GROWTH is on and the approved
strategy allows them. Publishing and Meta reads also need their deployment
modes set to live. A run with nothing to do leaves no record.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.autonomy import AutonomousRun
from app.models.growth import GrowthAccount, GrowthCalendarItem
from app.services.growth.attribution import collect_ga4
from app.services.growth.common import growth_enabled, insights_mode, now
from app.services.growth.creative import produce_creative
from app.services.growth.insights import collect_account_insights, collect_media_insights
from app.services.growth.planner import plan_rolling_calendar
from app.services.growth.publisher import publish_due
from app.services.growth.strategy import active_strategy

CREATIVE_LEAD = timedelta(hours=72)


def _record(db: Session, tenant_id: UUID, kind: str, summary: str, status: str = "completed") -> None:
    db.add(
        AutonomousRun(
            tenant_id=tenant_id,
            status=status,
            trigger="schedule",
            workflow="social_growth",
            trigger_event=f"growth:{kind}"[:80],
            summary=summary[:2000],
            finished_at=now(),
        )
    )


def plan_tenant(db: Session, tenant_id: UUID) -> int:
    strategy = active_strategy(db, tenant_id)
    if not growth_enabled(db, tenant_id) or strategy is None or strategy.status != "approved":
        return 0
    result = plan_rolling_calendar(db, tenant_id=tenant_id, actor_id=None)
    changed = int(result.get("created") or 0) + int(result.get("replanned") or 0)
    if changed:
        _record(db, tenant_id, "plan", result.get("detail", ""))
    return changed


def prepare_tenant(db: Session, tenant_id: UUID, limit: int = 4) -> int:
    strategy = active_strategy(db, tenant_id)
    if not growth_enabled(db, tenant_id) or strategy is None or strategy.status != "approved" or not strategy.auto_create:
        return 0
    rows = db.scalars(
        select(GrowthCalendarItem)
        .where(
            GrowthCalendarItem.tenant_id == tenant_id,
            GrowthCalendarItem.deleted_at.is_(None),
            GrowthCalendarItem.status == "planned",
            GrowthCalendarItem.creative_id.is_(None),
            GrowthCalendarItem.planned_for <= now() + CREATIVE_LEAD,
            GrowthCalendarItem.planned_for > now(),
        )
        .order_by(GrowthCalendarItem.planned_for.asc())
        .limit(limit)
    ).all()
    produced = 0
    problems: list[str] = []
    for row in rows:
        try:
            produce_creative(db, tenant_id=tenant_id, actor_id=None, item_id=row.id)
            produced += 1
        except HTTPException as exc:
            problems.append(str(exc.detail))
    if produced or problems:
        _record(db, tenant_id, "create", f"Produced {produced} creative(s). {'; '.join(problems[:3])}", "completed" if not problems else "blocked")
    return produced


def publish_tenant(db: Session, tenant_id: UUID) -> int:
    published = publish_due(db, tenant_id=tenant_id)
    if published:
        _record(db, tenant_id, "publish", f"Published {published} post(s).")
    return published


def insights_tenant(db: Session, tenant_id: UUID) -> int:
    if insights_mode() != "live" or not growth_enabled(db, tenant_id):
        return 0
    stored = 0
    accounts = db.scalars(
        select(GrowthAccount).where(
            GrowthAccount.tenant_id == tenant_id,
            GrowthAccount.deleted_at.is_(None),
            GrowthAccount.provenance == "live",
            GrowthAccount.status.in_(["connected", "unverified", "missing_permissions"]),
        )
    ).all()
    for account in accounts:
        for collect in (collect_account_insights, collect_media_insights):
            result = collect(db, tenant_id=tenant_id, actor_id=None, account_id=account.id)
            stored += int(result.get("stored") or 0)
    if stored:
        _record(db, tenant_id, "insights", f"Stored {stored} provider reading(s).")
    return stored


def ga4_tenant(db: Session, tenant_id: UUID) -> int:
    if not growth_enabled(db, tenant_id):
        return 0
    result = collect_ga4(db, tenant_id=tenant_id, actor_id=None, days=3)
    return int(result.get("stored") or 0)


def automation_runs(db: Session, tenant_id: UUID, limit: int = 12) -> list[dict]:
    rows = db.scalars(
        select(AutonomousRun)
        .where(AutonomousRun.tenant_id == tenant_id, AutonomousRun.workflow == "social_growth", AutonomousRun.deleted_at.is_(None))
        .order_by(AutonomousRun.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": str(row.id),
            "status": row.status,
            "trigger": row.trigger,
            "kind": row.trigger_event,
            "summary": row.summary,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
        for row in rows
    ]
