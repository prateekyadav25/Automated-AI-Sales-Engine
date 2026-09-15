from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.signals import MLFeatureSnapshot, MLOutcomeLabel
from app.services.ml.catalog import TASKS
from app.services.ml.labels import ResolvedLabel, upsert_outcome
from app.services.ml.snapshots import record_feature_snapshot
from app.services.ml.timeutil import now_utc

OUTCOMES = {
    "LEAD_CONVERTED",
    "OPPORTUNITY_WON",
    "OPPORTUNITY_LOST",
    "CUSTOMER_RENEWED",
    "CUSTOMER_CHURNED",
    "CUSTOMER_EXPANDED",
}

OUTCOME_TASK = {
    "LEAD_CONVERTED": "LEAD_CONVERSION",
    "OPPORTUNITY_WON": "OPPORTUNITY_WIN",
    "OPPORTUNITY_LOST": "OPPORTUNITY_WIN",
    "CUSTOMER_RENEWED": "CUSTOMER_RENEWAL",
    "CUSTOMER_CHURNED": "CUSTOMER_CHURN",
    "CUSTOMER_EXPANDED": "EXPANSION_PROPENSITY",
}


def record_features(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    customer_id: UUID | None,
    entity_type: str,
    entity_id: str,
    features: dict,
    ruleset_version: str = "rules-v2",
    task_key: str = "",
    as_of: datetime | None = None,
    source_versions: dict | None = None,
    feature_set_version: str = "v1",
) -> MLFeatureSnapshot:
    resolved_task = task_key or ("CUSTOMER_CHURN" if entity_type == "customer" else "")
    return record_feature_snapshot(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        customer_id=customer_id,
        entity_type=entity_type,
        entity_id=entity_id,
        task_key=resolved_task,
        features=features,
        source_versions=source_versions,
        feature_set_version=feature_set_version,
        as_of=as_of or now_utc(),
        ruleset_version=ruleset_version,
    )


def record_outcome(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    entity_type: str,
    entity_id: str,
    outcome_type: str,
    evidence: dict | None = None,
    occurred_at: datetime | None = None,
    feature_snapshot_id: UUID | None = None,
) -> MLOutcomeLabel | None:
    if outcome_type not in OUTCOMES:
        return None
    task_key = OUTCOME_TASK[outcome_type]
    status = "NEGATIVE" if outcome_type == "OPPORTUNITY_LOST" else "POSITIVE"
    if outcome_type == "OPPORTUNITY_LOST":
        task_key = "OPPORTUNITY_WIN"
    resolved = ResolvedLabel(status, 1 if status == "POSITIVE" else 0, occurred_at or now_utc(), evidence or {})
    if task_key not in TASKS:
        return None
    return upsert_outcome(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        task_key=task_key,
        entity_type=entity_type,
        entity_id=entity_id,
        resolved=resolved,
        feature_snapshot_id=feature_snapshot_id,
    )
