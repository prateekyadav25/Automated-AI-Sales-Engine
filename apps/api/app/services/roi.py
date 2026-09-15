from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval, ModelUsage
from app.models.autonomy import AutonomousRunStep
from app.models.crm import Activity, Lead, Opportunity
from app.models.identity import AuditLog
from app.models.lifecycle import Campaign, MeetingRecord
from app.models.pilot import ManualOverride

HUMAN_ACTIVITY = {"email", "call", "meeting", "task", "note", "stage_change"}


def _count(db: Session, stmt) -> int:
    return int(db.scalar(stmt) or 0)


def human_touches(db: Session, *, tenant_id: UUID, entity_type: str, entity_id: str, before: datetime | None = None) -> int:
    stmt = select(func.count()).select_from(Activity).where(
        Activity.tenant_id == tenant_id,
        Activity.entity_type == entity_type,
        Activity.entity_id == entity_id,
        Activity.actor_type == "human",
        Activity.deleted_at.is_(None),
    )
    if before is not None:
        stmt = stmt.where(Activity.created_at <= before)
    activities = _count(db, stmt)
    approvals = _count(
        db,
        select(func.count()).select_from(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.entity_type == entity_type,
            AIApproval.entity_id == entity_id,
            AIApproval.status.in_(["approved", "rejected", "edited"]),
            AIApproval.deleted_at.is_(None),
        ),
    )
    edits = _count(
        db,
        select(func.count()).select_from(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
            AuditLog.action.in_(["opportunity.update", "lead.update", "customer.update", "account.update"]),
        ),
    )
    return activities + approvals + edits


def automation_metrics(db: Session, *, tenant_id: UUID) -> dict:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    automated = _count(
        db,
        select(func.count()).select_from(Activity).where(
            Activity.tenant_id == tenant_id,
            Activity.actor_type == "ai",
            Activity.created_at >= start,
            Activity.deleted_at.is_(None),
        ),
    )
    approvals = _count(
        db,
        select(func.count()).select_from(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.created_at >= start,
            AIApproval.deleted_at.is_(None),
        ),
    )
    decided = db.scalars(
        select(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.status.in_(["approved", "rejected"]),
            AIApproval.deleted_at.is_(None),
        )
    ).all()
    durations = []
    for row in decided:
        if row.updated_at and row.created_at:
            durations.append((row.updated_at - row.created_at).total_seconds())
    overrides = _count(db, select(func.count()).select_from(ManualOverride).where(ManualOverride.tenant_id == tenant_id, ManualOverride.deleted_at.is_(None)))
    steps = _count(
        db,
        select(func.count()).select_from(AutonomousRunStep).where(
            AutonomousRunStep.tenant_id == tenant_id,
            AutonomousRunStep.status.in_(["completed", "ok"]),
            AutonomousRunStep.deleted_at.is_(None),
            AutonomousRunStep.created_at >= start,
        ),
    )
    eligible = automated + approvals + overrides
    return {
        "automated_internal_tasks": automated,
        "approval_actions": approvals,
        "manual_overrides": overrides,
        "autonomous_run_steps": steps,
        "average_approval_seconds": round(sum(durations) / len(durations), 1) if durations else None,
        "autonomous_execution_rate": round(automated / eligible, 4) if eligible else None,
        "methodology": "Autonomous Execution Rate = automatable actions executed by the system / eligible actions. Not employee replacement.",
    }


def touches_report(db: Session, *, tenant_id: UUID) -> dict:
    leads = db.scalars(select(Lead).where(Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None))).all()[:50]
    opps = db.scalars(select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.deleted_at.is_(None))).all()[:50]
    lead_touches = [human_touches(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(row.id)) for row in leads]
    opp_touches = [human_touches(db, tenant_id=tenant_id, entity_type="opportunity", entity_id=str(row.id)) for row in opps]
    return {
        "human_touches_before_qualification": round(sum(lead_touches) / len(lead_touches), 2) if lead_touches else None,
        "human_touches_before_close": round(sum(opp_touches) / len(opp_touches), 2) if opp_touches else None,
        "sample_leads": len(lead_touches),
        "sample_opportunities": len(opp_touches),
    }


def ai_prepared_pipeline(db: Session, *, tenant_id: UUID) -> dict:
    discovered = _count(db, select(func.count()).select_from(Lead).where(Lead.tenant_id == tenant_id, Lead.source == "ai_discovery", Lead.deleted_at.is_(None)))
    total = _count(db, select(func.count()).select_from(Lead).where(Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None)))
    meetings = _count(db, select(func.count()).select_from(MeetingRecord).where(MeetingRecord.tenant_id == tenant_id, MeetingRecord.deleted_at.is_(None)))
    return {
        "ai_discovery_leads": discovered,
        "all_leads": total,
        "meetings": meetings,
        "revenue_associated_note": "Revenue associated with AI-prepared opportunities uses source provenance. The OS does not claim invented AI revenue.",
    }


def campaign_attribution(db: Session, *, tenant_id: UUID) -> dict:
    campaigns = db.scalars(select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.deleted_at.is_(None))).all()
    rows = []
    for campaign in campaigns:
        won = db.scalars(
            select(Opportunity).where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.campaign_id == campaign.id,
                Opportunity.stage == "closed_won",
                Opportunity.deleted_at.is_(None),
            )
        ).all()
        spend = Decimal(str(campaign.spent or 0))
        revenue = sum((Decimal(str(item.amount or 0)) for item in won), Decimal("0"))
        rows.append(
            {
                "campaign_id": str(campaign.id),
                "name": campaign.name,
                "channel": campaign.channel,
                "spend": float(spend),
                "closed_won_revenue": float(revenue),
                "closed_won_count": len(won),
                "roas": float(revenue / spend) if spend > 0 else None,
                "methodology": "ROAS = closed-won opportunity amount attributed by campaign_id / persisted campaign.spent. No invented revenue.",
            }
        )
    return {
        "campaigns": rows,
        "methodology": "Attribution is first-touch campaign_id copied from inbound capture onto Lead and Opportunity. Spend is provider-synced, not estimated.",
    }


def usage_costs(db: Session, *, tenant_id: UUID) -> dict:
    start = datetime.now(UTC) - timedelta(days=1)
    rows = db.scalars(select(ModelUsage).where(ModelUsage.tenant_id == tenant_id, ModelUsage.created_at >= start)).all()
    total = float(sum(float(row.estimated_cost or 0) for row in rows))
    by_agent: dict[str, float] = {}
    for row in rows:
        by_agent[row.agent] = by_agent.get(row.agent, 0) + float(row.estimated_cost or 0)
    return {
        "estimated_cost_24h": round(total, 6),
        "calls_24h": len(rows),
        "by_agent": {key: round(value, 6) for key, value in by_agent.items()},
        "prompts_omitted": True,
    }
