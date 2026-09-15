from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Customer, Lead, Opportunity, Renewal
from app.models.identity import DomainEvent
from app.models.ml import OpportunityFieldHistory
from app.models.post_sale import ExpansionRecommendation
from app.models.signals import MLOutcomeLabel
from app.services.ml.catalog import TASKS
from app.services.ml.timeutil import aware_dt, now_utc

OUTCOME_FOR_TASK = {
    "LEAD_CONVERSION": "LEAD_CONVERTED",
    "OPPORTUNITY_WIN": "OPPORTUNITY_WON",
    "CLOSE_DATE_SLIPPAGE": "CLOSE_DATE_SLIPPED",
    "CUSTOMER_CHURN": "CUSTOMER_CHURNED",
    "CUSTOMER_RENEWAL": "CUSTOMER_RENEWED",
    "EXPANSION_PROPENSITY": "CUSTOMER_EXPANDED",
    "PRODUCT_AFFINITY": "PRODUCT_ADOPTED",
    "CUSTOMER_LIFETIME_VALUE": "LTV_OBSERVED",
    "FORECAST_CALIBRATION": "FORECAST_ACTUALIZED",
}


class ResolvedLabel:
    def __init__(self, status: str, value: int | None, occurred_at: datetime | None, evidence: dict):
        self.status = status
        self.value = value
        self.occurred_at = occurred_at
        self.evidence = evidence


def _events(db: Session, tenant_id: UUID, entity_type: str, entity_id: str, event_type: str) -> list[DomainEvent]:
    return list(
        db.scalars(
            select(DomainEvent).where(
                DomainEvent.tenant_id == tenant_id,
                DomainEvent.entity_type == entity_type,
                DomainEvent.entity_id == entity_id,
                DomainEvent.event_type == event_type,
            )
        ).all()
    )


def resolve_label(
    db: Session,
    *,
    tenant_id: UUID,
    task_key: str,
    entity_type: str,
    entity_id: str,
    as_of: datetime,
    now: datetime | None = None,
) -> ResolvedLabel:
    spec = TASKS[task_key]
    horizon = spec["horizon"]
    moment = aware_dt(now) or now_utc()
    start = aware_dt(as_of) or moment
    deadline = start + timedelta(days=horizon)
    mature = moment >= deadline

    if task_key == "LEAD_CONVERSION":
        qualified = _events(db, tenant_id, "lead", entity_id, "lead.qualified")
        hit = next((aware_dt(row.created_at) for row in qualified if aware_dt(row.created_at) and aware_dt(row.created_at) > start), None)
        lead = db.get(Lead, UUID(entity_id))
        if hit and hit <= deadline:
            return ResolvedLabel("POSITIVE", 1, hit, {"event": "lead.qualified"})
        if lead and lead.status == "converted" and (aware_dt(lead.updated_at) or moment) > start:
            occurred = aware_dt(lead.updated_at)
            if occurred and occurred <= deadline:
                return ResolvedLabel("POSITIVE", 1, occurred, {"status": "converted"})
        if not mature:
            return ResolvedLabel("PENDING" if moment < deadline else "CENSORED", None, None, {"horizon": horizon})
        return ResolvedLabel("NEGATIVE", 0, None, {"horizon_elapsed": True})

    if task_key == "OPPORTUNITY_WIN":
        changes = db.scalars(
            select(OpportunityFieldHistory).where(
                OpportunityFieldHistory.tenant_id == tenant_id,
                OpportunityFieldHistory.opportunity_id == UUID(entity_id),
                OpportunityFieldHistory.field_name == "stage",
                OpportunityFieldHistory.changed_at > start,
                OpportunityFieldHistory.changed_at <= deadline,
                OpportunityFieldHistory.deleted_at.is_(None),
            )
        ).all()
        won = next((row for row in changes if row.new_value == "closed_won"), None)
        lost = next((row for row in changes if row.new_value == "closed_lost"), None)
        opp = db.get(Opportunity, UUID(entity_id))
        if won:
            return ResolvedLabel("POSITIVE", 1, aware_dt(won.changed_at), {"stage": "closed_won"})
        if lost:
            return ResolvedLabel("NEGATIVE", 0, aware_dt(lost.changed_at), {"stage": "closed_lost"})
        if opp and opp.stage == "closed_won" and (aware_dt(opp.updated_at) or moment) > start:
            occurred = aware_dt(opp.updated_at)
            if occurred and occurred <= deadline:
                return ResolvedLabel("POSITIVE", 1, occurred, {"stage": "closed_won", "source": "current"})
        if opp and opp.stage == "closed_lost":
            return ResolvedLabel("NEGATIVE", 0, aware_dt(opp.updated_at), {"stage": "closed_lost"})
        if not mature:
            return ResolvedLabel("PENDING", None, None, {"horizon": horizon})
        return ResolvedLabel("NEGATIVE", 0, None, {"still_open": True})

    if task_key == "CLOSE_DATE_SLIPPAGE":
        slips = db.scalars(
            select(OpportunityFieldHistory).where(
                OpportunityFieldHistory.tenant_id == tenant_id,
                OpportunityFieldHistory.opportunity_id == UUID(entity_id),
                OpportunityFieldHistory.field_name == "expected_close",
                OpportunityFieldHistory.changed_at > start,
                OpportunityFieldHistory.changed_at <= deadline,
                OpportunityFieldHistory.deleted_at.is_(None),
            )
        ).all()
        slipped = [row for row in slips if str(row.new_value) > str(row.old_value)]
        if slipped:
            return ResolvedLabel("POSITIVE", 1, aware_dt(slipped[0].changed_at), {"count": len(slipped)})
        if not mature:
            return ResolvedLabel("PENDING", None, None, {"horizon": horizon})
        return ResolvedLabel("NEGATIVE", 0, None, {"no_slip": True})

    if task_key in {"CUSTOMER_CHURN", "CUSTOMER_RENEWAL"}:
        customer = db.get(Customer, UUID(entity_id))
        renewal = db.scalar(
            select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.customer_id == UUID(entity_id), Renewal.deleted_at.is_(None))
        )
        churned = bool(customer and customer.status in {"churned", "terminated", "lost"})
        renewed = bool(renewal and renewal.status in {"renewed", "won", "completed"})
        failed = bool(renewal and renewal.status in {"lost", "churned", "failed"})
        if task_key == "CUSTOMER_CHURN":
            if churned or failed:
                return ResolvedLabel("POSITIVE", 1, aware_dt(customer.updated_at if customer else None), {"status": customer.status if customer else ""})
            if not mature:
                return ResolvedLabel("PENDING", None, None, {"horizon": horizon})
            return ResolvedLabel("NEGATIVE", 0, None, {"still_active": True})
        if renewed:
            return ResolvedLabel("POSITIVE", 1, aware_dt(renewal.updated_at if renewal else None), {"renewal": renewal.status if renewal else ""})
        if churned or failed:
            return ResolvedLabel("NEGATIVE", 0, aware_dt(customer.updated_at if customer else None), {"churned": True})
        if not mature:
            return ResolvedLabel("PENDING", None, None, {"horizon": horizon})
        return ResolvedLabel("NEGATIVE", 0, None, {"not_renewed": True})

    if task_key == "EXPANSION_PROPENSITY":
        recs = db.scalars(
            select(ExpansionRecommendation).where(
                ExpansionRecommendation.tenant_id == tenant_id,
                ExpansionRecommendation.customer_id == UUID(entity_id),
                ExpansionRecommendation.deleted_at.is_(None),
            )
        ).all()
        won = next((row for row in recs if row.opportunity_id and row.status in {"won", "converted"}), None)
        if won:
            return ResolvedLabel("POSITIVE", 1, aware_dt(won.updated_at), {"recommendation_id": str(won.id)})
        if not mature:
            return ResolvedLabel("PENDING", None, None, {"horizon": horizon})
        return ResolvedLabel("NEGATIVE", 0, None, {"no_won_expansion": True})

    if not mature:
        return ResolvedLabel("CENSORED", None, None, {"horizon": horizon, "task": task_key})
    return ResolvedLabel("NEGATIVE", 0, None, {"default": True})


def upsert_outcome(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    task_key: str,
    entity_type: str,
    entity_id: str,
    resolved: ResolvedLabel,
    feature_snapshot_id: UUID | None = None,
    label_version: str = "v1",
) -> MLOutcomeLabel:
    spec = TASKS[task_key]
    row = db.scalar(
        select(MLOutcomeLabel).where(
            MLOutcomeLabel.tenant_id == tenant_id,
            MLOutcomeLabel.entity_type == entity_type,
            MLOutcomeLabel.entity_id == entity_id,
            MLOutcomeLabel.task_key == task_key,
            MLOutcomeLabel.label_version == label_version,
            MLOutcomeLabel.deleted_at.is_(None),
        )
    )
    if row is None:
        row = MLOutcomeLabel(
            tenant_id=tenant_id,
            created_by=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            outcome_type=OUTCOME_FOR_TASK[task_key],
            task_key=task_key,
            label_version=label_version,
            horizon_days=spec["horizon"],
        )
        db.add(row)
    row.label_status = resolved.status
    row.occurred_at = resolved.occurred_at
    row.label_observed_at = now_utc() if resolved.status in {"POSITIVE", "NEGATIVE"} else None
    row.feature_snapshot_id = feature_snapshot_id or row.feature_snapshot_id
    row.evidence_json = json.dumps(resolved.evidence, default=str)[:4000]
    db.flush()
    return row
