from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import ModelUsage
from app.models.autonomy import AutopilotSettings


def ai_spend_today(db: Session, tenant_id: UUID) -> float:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.scalars(
        select(ModelUsage).where(ModelUsage.tenant_id == tenant_id, ModelUsage.created_at >= start)
    ).all()
    return float(sum(float(row.estimated_cost or 0) for row in rows))


def ai_budget_reason(db: Session, settings: AutopilotSettings) -> str | None:
    budget = float(settings.ai_daily_budget or 0)
    if budget <= 0:
        return None
    if ai_spend_today(db, settings.tenant_id) >= budget:
        return "AI daily budget exceeded"
    return None
