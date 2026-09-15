from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.autonomy import AutonomousRunStep
from app.models.crm import Customer, Lead, Opportunity, Renewal
from app.models.integrations import ProviderAction
from app.models.lifecycle import MeetingRecord
from app.models.pilot import OperatorBrief
from app.services.data_quality import learning_progress
from app.services.roi import automation_metrics


def _count(db: Session, stmt) -> int:
    return int(db.scalar(stmt) or 0)


def generate_brief(db: Session, *, tenant_id: UUID, actor_id: UUID | None, kind: str) -> OperatorBrief:
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "weekly":
        start = now - timedelta(days=7)
    payload = {
        "qualified_leads": _count(
            db,
            select(func.count()).select_from(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.status.in_(["qualified", "converted"]),
                Lead.created_at >= start,
                Lead.deleted_at.is_(None),
            ),
        ),
        "meetings": _count(
            db,
            select(func.count()).select_from(MeetingRecord).where(
                MeetingRecord.tenant_id == tenant_id,
                MeetingRecord.created_at >= start,
                MeetingRecord.deleted_at.is_(None),
            ),
        ),
        "deals_at_risk": _count(
            db,
            select(func.count()).select_from(Opportunity).where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.stage.notin_(["closed_won", "closed_lost"]),
                Opportunity.deleted_at.is_(None),
            ),
        ),
        "customers_at_risk": _count(
            db,
            select(func.count()).select_from(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.status.in_(["at_risk", "churned"]),
                Customer.deleted_at.is_(None),
            ),
        ),
        "renewals": _count(db, select(func.count()).select_from(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.deleted_at.is_(None))),
        "failed_automations": _count(
            db,
            select(func.count()).select_from(AutonomousRunStep).where(
                AutonomousRunStep.tenant_id == tenant_id,
                AutonomousRunStep.status.in_(["FAILED", "failed"]),
                AutonomousRunStep.created_at >= start,
            ),
        ),
        "approvals_waiting": _count(
            db,
            select(func.count()).select_from(AIApproval).where(
                AIApproval.tenant_id == tenant_id,
                AIApproval.status == "pending",
                AIApproval.deleted_at.is_(None),
            ),
        ),
        "provider_failures": _count(
            db,
            select(func.count()).select_from(ProviderAction).where(
                ProviderAction.tenant_id == tenant_id,
                ProviderAction.status.in_(["FAILED", "DEAD_LETTER"]),
                ProviderAction.created_at >= start,
            ),
        ),
        "automation": automation_metrics(db, tenant_id=tenant_id),
    }
    if kind == "weekly":
        payload["learning"] = [
            {"task_key": row["task_key"], "status": row["recommended_status"], "rows": row["rows"], "positive": row["positive"]}
            for row in learning_progress(db, tenant_id=tenant_id)
        ]
    row = OperatorBrief(
        tenant_id=tenant_id,
        created_by=actor_id,
        kind=kind,
        period_start=start,
        period_end=now,
        payload_json=json.dumps(payload, default=str),
    )
    db.add(row)
    db.flush()
    return row
