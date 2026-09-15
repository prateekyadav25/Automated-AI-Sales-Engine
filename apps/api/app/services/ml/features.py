from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.crm import Activity, LeadScore, Opportunity
from app.models.lifecycle import ForecastSnapshot, MeetingRecord
from app.models.ml import OpportunityFieldHistory
from app.models.post_sale import HealthScoreSnapshot
from app.models.signals import FinanceSnapshot, SupportSnapshot, UsageRollup
from app.services.ml.catalog import FEATURE_DEFINITIONS, TASKS, forbidden_features
from app.services.ml.timeutil import aware_dt, now_utc, truncate_seconds


class FeatureComputation:
    def __init__(self, features: dict, source_versions: dict):
        self.features = features
        self.source_versions = source_versions


def _iso(value: datetime | None) -> str | None:
    stamped = aware_dt(value)
    return stamped.isoformat() if stamped else None


def _count_activities(
    db: Session, tenant_id: UUID, entity_type: str, entity_id: str, as_of: datetime, days: int, kinds: set[str]
) -> tuple[int, datetime | None]:
    start = as_of - timedelta(days=days)
    rows = db.scalars(
        select(Activity).where(
            Activity.tenant_id == tenant_id,
            Activity.entity_type == entity_type,
            Activity.entity_id == entity_id,
            Activity.deleted_at.is_(None),
            Activity.activity_type.in_(kinds),
            Activity.created_at <= as_of,
            Activity.created_at >= start,
        )
    ).all()
    latest = max((aware_dt(row.created_at) for row in rows if row.created_at), default=None)
    return len(rows), latest


def _count_meetings(
    db: Session, tenant_id: UUID, *, lead_id: UUID | None, opportunity_id: UUID | None, as_of: datetime, days: int
) -> tuple[int, datetime | None]:
    start = as_of - timedelta(days=days)
    stmt = select(MeetingRecord).where(
        MeetingRecord.tenant_id == tenant_id,
        MeetingRecord.deleted_at.is_(None),
        func.coalesce(MeetingRecord.occurred_at, MeetingRecord.start_at, MeetingRecord.created_at) <= as_of,
        func.coalesce(MeetingRecord.occurred_at, MeetingRecord.start_at, MeetingRecord.created_at) >= start,
    )
    if lead_id:
        stmt = stmt.where(MeetingRecord.lead_id == lead_id)
    if opportunity_id:
        stmt = stmt.where(MeetingRecord.opportunity_id == opportunity_id)
    rows = db.scalars(stmt).all()
    times = [aware_dt(row.occurred_at or row.start_at or row.created_at) for row in rows]
    latest = max((t for t in times if t), default=None)
    return len(rows), latest


def _latest_lead_score(db: Session, lead_id: UUID, as_of: datetime) -> LeadScore | None:
    return db.scalar(
        select(LeadScore)
        .where(LeadScore.lead_id == lead_id, LeadScore.deleted_at.is_(None), LeadScore.created_at <= as_of)
        .order_by(LeadScore.created_at.desc())
    )


def _field_as_of(db: Session, tenant_id: UUID, opportunity_id: UUID, field: str, as_of: datetime) -> str | None:
    row = db.scalar(
        select(OpportunityFieldHistory)
        .where(
            OpportunityFieldHistory.tenant_id == tenant_id,
            OpportunityFieldHistory.opportunity_id == opportunity_id,
            OpportunityFieldHistory.field_name == field,
            OpportunityFieldHistory.changed_at <= as_of,
            OpportunityFieldHistory.deleted_at.is_(None),
        )
        .order_by(OpportunityFieldHistory.changed_at.desc())
    )
    if row is None:
        return None
    return row.new_value


def compute_features(
    db: Session,
    *,
    tenant_id: UUID,
    task_key: str,
    entity_type: str,
    entity_id: str,
    as_of: datetime | None = None,
) -> FeatureComputation:
    if task_key not in TASKS:
        raise ValueError(f"Unknown task {task_key}")
    stamped = truncate_seconds(as_of or now_utc())
    features: dict = {}
    sources: dict = {}
    expected = TASKS[task_key]["entity_type"]
    if entity_type != expected:
        raise ValueError(f"{task_key} expects entity_type={expected}")

    emails, email_at = _count_activities(db, tenant_id, entity_type, entity_id, stamped, 30, {"email", "outbound", "reply"})
    if entity_type == "lead":
        meetings, meet_at = _count_meetings(db, tenant_id, lead_id=UUID(entity_id), opportunity_id=None, as_of=stamped, days=30)
        score = _latest_lead_score(db, UUID(entity_id), stamped)
        features["lead_icp_score"] = score.icp_fit if score else 0
        features["lead_intent_score"] = score.intent if score else 0
        features["lead_engagement_score"] = score.engagement if score else 0
        features["emails_last_30d"] = emails
        features["meetings_last_30d"] = meetings
        sources["lead_icp_score"] = {"source": "lead_scores", "max_observed_at": _iso(score.created_at if score else None)}
        sources["emails_last_30d"] = {"source": "activities", "max_observed_at": _iso(email_at)}
        sources["meetings_last_30d"] = {"source": "meetings", "max_observed_at": _iso(meet_at)}
    elif entity_type == "opportunity":
        meetings, meet_at = _count_meetings(db, tenant_id, lead_id=None, opportunity_id=UUID(entity_id), as_of=stamped, days=30)
        opp = db.get(Opportunity, UUID(entity_id))
        last_stage = db.scalar(
            select(OpportunityFieldHistory)
            .where(
                OpportunityFieldHistory.tenant_id == tenant_id,
                OpportunityFieldHistory.opportunity_id == UUID(entity_id),
                OpportunityFieldHistory.field_name == "stage",
                OpportunityFieldHistory.changed_at <= stamped,
                OpportunityFieldHistory.deleted_at.is_(None),
            )
            .order_by(OpportunityFieldHistory.changed_at.desc())
        )
        if last_stage and last_stage.changed_at:
            days_in_stage = max(0, (stamped - (aware_dt(last_stage.changed_at) or stamped)).days)
            stage_at = last_stage.changed_at
        else:
            created = aware_dt(opp.created_at) if opp else stamped
            days_in_stage = max(0, (stamped - (created or stamped)).days)
            stage_at = created
        close_changes = (
            db.scalar(
                select(func.count()).where(
                    OpportunityFieldHistory.tenant_id == tenant_id,
                    OpportunityFieldHistory.opportunity_id == UUID(entity_id),
                    OpportunityFieldHistory.field_name == "expected_close",
                    OpportunityFieldHistory.changed_at <= stamped,
                    OpportunityFieldHistory.deleted_at.is_(None),
                )
            )
            or 0
        )
        prob_raw = _field_as_of(db, tenant_id, UUID(entity_id), "probability", stamped)
        if prob_raw is None and opp and (aware_dt(opp.created_at) or stamped) <= stamped:
            prob_raw = str(opp.probability)
        features["days_in_stage"] = days_in_stage
        features["close_date_change_count"] = int(close_changes)
        features["stage_probability"] = int(float(prob_raw)) if prob_raw not in {None, ""} else None
        features["emails_last_30d"] = emails
        features["meetings_last_30d"] = meetings
        sources["days_in_stage"] = {"source": "opportunity_field_history", "max_observed_at": _iso(stage_at)}
        sources["emails_last_30d"] = {"source": "activities", "max_observed_at": _iso(email_at)}
        sources["meetings_last_30d"] = {"source": "meetings", "max_observed_at": _iso(meet_at)}
    elif entity_type == "customer":
        customer_id = UUID(entity_id)
        health = db.scalar(
            select(HealthScoreSnapshot)
            .where(
                HealthScoreSnapshot.tenant_id == tenant_id,
                HealthScoreSnapshot.customer_id == customer_id,
                HealthScoreSnapshot.deleted_at.is_(None),
                func.coalesce(HealthScoreSnapshot.calculated_at, HealthScoreSnapshot.created_at) <= stamped,
            )
            .order_by(func.coalesce(HealthScoreSnapshot.calculated_at, HealthScoreSnapshot.created_at).desc())
        )
        rollup = db.scalar(
            select(UsageRollup)
            .where(
                UsageRollup.tenant_id == tenant_id,
                UsageRollup.customer_id == customer_id,
                UsageRollup.deleted_at.is_(None),
                UsageRollup.period_start <= stamped,
            )
            .order_by(UsageRollup.period_start.desc())
        )
        support = db.scalar(
            select(SupportSnapshot)
            .where(
                SupportSnapshot.tenant_id == tenant_id,
                SupportSnapshot.customer_id == customer_id,
                SupportSnapshot.deleted_at.is_(None),
                func.coalesce(SupportSnapshot.last_event_at, SupportSnapshot.opened_at, SupportSnapshot.created_at) <= stamped,
            )
            .order_by(func.coalesce(SupportSnapshot.last_event_at, SupportSnapshot.created_at).desc())
        )
        finance = db.scalar(
            select(FinanceSnapshot)
            .where(
                FinanceSnapshot.tenant_id == tenant_id,
                FinanceSnapshot.customer_id == customer_id,
                FinanceSnapshot.deleted_at.is_(None),
                func.coalesce(FinanceSnapshot.last_event_at, FinanceSnapshot.created_at) <= stamped,
            )
            .order_by(func.coalesce(FinanceSnapshot.last_event_at, FinanceSnapshot.created_at).desc())
        )
        trend = 0
        if rollup and rollup.trend_30d == "declining":
            trend = -1
        elif rollup and rollup.trend_30d == "increasing":
            trend = 1
        features["customer_health_score"] = health.total if health else None
        features["usage_30d_change"] = trend if rollup else None
        features["critical_support_tickets"] = (support.open_critical or 0) if support else 0
        features["days_past_due"] = (finance.days_past_due or 0) if finance else 0
        sources["customer_health_score"] = {
            "source": "health_score_snapshots",
            "max_observed_at": _iso(health.calculated_at if health else None),
        }
        sources["usage_30d_change"] = {"source": "usage_rollups", "max_observed_at": _iso(rollup.period_start if rollup else None)}
        sources["critical_support_tickets"] = {
            "source": "support_snapshots",
            "max_observed_at": _iso(support.last_event_at if support else None),
        }
        sources["days_past_due"] = {"source": "finance_snapshots", "max_observed_at": _iso(finance.last_event_at if finance else None)}
    elif entity_type == "forecast":
        snap = db.scalar(
            select(ForecastSnapshot)
            .where(
                ForecastSnapshot.tenant_id == tenant_id,
                ForecastSnapshot.deleted_at.is_(None),
                ForecastSnapshot.created_at <= stamped,
            )
            .order_by(ForecastSnapshot.created_at.desc())
        )
        features["weighted_pipeline"] = float(snap.weighted) if snap else None
        sources["weighted_pipeline"] = {"source": "forecast_snapshots", "max_observed_at": _iso(snap.created_at if snap else None)}

    banned = forbidden_features(task_key)
    leak = banned.intersection(features)
    if leak:
        raise ValueError(f"Forbidden leakage features present: {sorted(leak)}")
    for name, meta in sources.items():
        observed = meta.get("max_observed_at")
        if observed and datetime.fromisoformat(observed) > stamped:
            raise ValueError(f"Feature {name} observed after as_of")
    _ = FEATURE_DEFINITIONS
    return FeatureComputation(features, sources)
