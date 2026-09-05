from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval, KnowledgeSource
from app.models.crm import Account, Activity, Lead, LeadScore, Opportunity, Task
from app.schemas.crm import ActivityOut, KPIOut, OpportunityOut, StageMixOut, TaskOut


def kpis(db: Session, tenant_id: UUID) -> KPIOut:
    leads = db.scalar(
        select(func.count()).where(Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None))
    ) or 0
    latest_scores = (
        select(LeadScore.lead_id, func.max(LeadScore.created_at).label("mx"))
        .where(LeadScore.tenant_id == tenant_id)
        .group_by(LeadScore.lead_id)
        .subquery()
    )
    mql = db.scalar(
        select(func.count())
        .select_from(LeadScore)
        .join(
            latest_scores,
            (LeadScore.lead_id == latest_scores.c.lead_id)
            & (LeadScore.created_at == latest_scores.c.mx),
        )
        .where(LeadScore.tenant_id == tenant_id, LeadScore.total >= 60)
    ) or 0
    sql = db.scalar(
        select(func.count()).where(
            Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None), Lead.status == "qualified"
        )
    ) or 0
    accounts = db.scalar(
        select(func.count()).where(Account.tenant_id == tenant_id, Account.deleted_at.is_(None))
    ) or 0
    open_opps = db.scalar(
        select(func.count()).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.stage.notin_(["closed_won", "closed_lost"]),
        )
    ) or 0
    won = db.scalar(
        select(func.count()).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.stage == "closed_won",
        )
    ) or 0
    lost = db.scalar(
        select(func.count()).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.stage == "closed_lost",
        )
    ) or 0
    open_value = db.scalar(
        select(func.coalesce(func.sum(Opportunity.amount), 0)).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.stage.notin_(["closed_won", "closed_lost"]),
        )
    ) or 0
    weighted = db.scalar(
        select(
            func.coalesce(func.sum(Opportunity.amount * Opportunity.probability / 100), 0)
        ).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.stage.notin_(["closed_won", "closed_lost"]),
        )
    ) or 0
    decided = int(won) + int(lost)
    win_rate = float(won) / decided if decided else 0.0
    tasks_open = db.scalar(
        select(func.count()).where(
            Task.tenant_id == tenant_id, Task.deleted_at.is_(None), Task.status == "open"
        )
    ) or 0
    overdue = db.scalar(
        select(func.count()).where(
            Task.tenant_id == tenant_id,
            Task.deleted_at.is_(None),
            Task.status == "open",
            Task.due_at.is_not(None),
            Task.due_at < datetime.now(UTC),
        )
    ) or 0
    approvals = db.scalar(
        select(func.count()).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.deleted_at.is_(None),
            AIApproval.status == "pending",
        )
    ) or 0
    knowledge = db.scalar(
        select(func.count()).where(
            KnowledgeSource.tenant_id == tenant_id, KnowledgeSource.deleted_at.is_(None)
        )
    ) or 0
    return KPIOut(
        total_leads=int(leads),
        mql_count=int(mql),
        sql_count=int(sql),
        total_accounts=int(accounts),
        open_opportunities=int(open_opps),
        won_opportunities=int(won),
        open_pipeline_value=Decimal(str(open_value)),
        weighted_pipeline_value=Decimal(str(weighted)),
        win_rate=round(win_rate, 4),
        tasks_open=int(tasks_open),
        tasks_overdue=int(overdue),
        pending_approvals=int(approvals),
        knowledge_sources=int(knowledge),
    )


def pipeline_mix(db: Session, tenant_id: UUID) -> list[StageMixOut]:
    rows = db.execute(
        select(
            Opportunity.stage,
            func.count().label("count"),
            func.coalesce(func.sum(Opportunity.amount), 0).label("amount"),
        )
        .where(Opportunity.tenant_id == tenant_id, Opportunity.deleted_at.is_(None))
        .group_by(Opportunity.stage)
    ).all()
    return [StageMixOut(stage=row.stage, count=int(row.count), amount=Decimal(str(row.amount))) for row in rows]


def recent_activities(db: Session, tenant_id: UUID, limit: int = 8) -> list[ActivityOut]:
    rows = db.scalars(
        select(Activity)
        .where(Activity.tenant_id == tenant_id, Activity.deleted_at.is_(None))
        .order_by(Activity.created_at.desc())
        .limit(limit)
    ).all()
    return [ActivityOut.model_validate(row) for row in rows]


def overdue_tasks(db: Session, tenant_id: UUID, limit: int = 8) -> list[TaskOut]:
    rows = db.scalars(
        select(Task)
        .where(
            Task.tenant_id == tenant_id,
            Task.deleted_at.is_(None),
            Task.status == "open",
            Task.due_at.is_not(None),
            Task.due_at < datetime.now(UTC),
        )
        .order_by(Task.due_at.asc())
        .limit(limit)
    ).all()
    return [TaskOut.model_validate(row) for row in rows]


def at_risk_opportunities(db: Session, tenant_id: UUID, limit: int = 6) -> list[OpportunityOut]:
    rows = db.scalars(
        select(Opportunity)
        .where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.stage.notin_(["closed_won", "closed_lost"]),
        )
        .order_by(Opportunity.updated_at.asc())
        .limit(limit)
    ).all()
    return [OpportunityOut.model_validate(row) for row in rows]
