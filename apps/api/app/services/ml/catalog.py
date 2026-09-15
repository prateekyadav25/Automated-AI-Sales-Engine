from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ml import FeatureSet, LabelDefinition, ModelVersion, PredictionTask

TASKS: dict[str, dict] = {
    "LEAD_CONVERSION": {
        "name": "Lead conversion",
        "entity_type": "lead",
        "horizon": 90,
        "label": "Lead became qualified within the horizon.",
        "positive": "lead.qualified event within horizon after as_of",
        "negative": "horizon elapsed with no qualification",
        "censor": "as_of + horizon is still in the future",
        "split": "Temporal 70/15/15 by as_of. All rows for one lead stay in the split of the earliest as_of.",
        "baseline": "rules-v1 lead score threshold",
        "forbidden": ["converted_at", "final_status", "opportunity_id"],
    },
    "OPPORTUNITY_WIN": {
        "name": "Opportunity win",
        "entity_type": "opportunity",
        "horizon": 120,
        "label": "Opportunity reached Closed Won within the horizon.",
        "positive": "stage became closed_won at or before as_of + horizon",
        "negative": "closed_lost or still open after horizon",
        "censor": "still open and horizon not elapsed",
        "split": "Temporal 70/15/15 by as_of. All rows for one opportunity stay together.",
        "baseline": "stage-weighted probability",
        "forbidden": ["closed_won_at", "final_stage", "final_contract_value"],
    },
    "CLOSE_DATE_SLIPPAGE": {
        "name": "Close date slippage",
        "entity_type": "opportunity",
        "horizon": 60,
        "label": "Expected close date moved later within the horizon.",
        "positive": "expected_close increased after as_of within horizon",
        "negative": "close date held or pulled in, or deal closed on original date",
        "censor": "horizon not elapsed and close date unchanged",
        "split": "Temporal 70/15/15 by as_of. One opportunity per split.",
        "baseline": "deal insight close-slip flag",
        "forbidden": ["final_close_date"],
    },
    "CUSTOMER_CHURN": {
        "name": "Customer churn",
        "entity_type": "customer",
        "horizon": 180,
        "label": "Customer terminated or failed renewal under policy.",
        "positive": "customer terminated or renewal failed within horizon",
        "negative": "customer still active after horizon",
        "censor": "horizon not elapsed",
        "split": "Temporal 70/15/15 by as_of. One customer per split.",
        "baseline": "rules-v2 customer risk",
        "forbidden": ["churned_at", "final_status"],
    },
    "CUSTOMER_RENEWAL": {
        "name": "Customer renewal",
        "entity_type": "customer",
        "horizon": 180,
        "label": "Renewal completed without churn.",
        "positive": "renewal status completed/won within horizon",
        "negative": "renewal lost or customer churned",
        "censor": "renewal window still open",
        "split": "Temporal 70/15/15 by as_of. One customer per split.",
        "baseline": "renewal readiness rules",
        "forbidden": ["renewed_at", "final_renewal_status"],
    },
    "EXPANSION_PROPENSITY": {
        "name": "Expansion propensity",
        "entity_type": "customer",
        "horizon": 180,
        "label": "New approved expansion opportunity won.",
        "positive": "expansion recommendation minted and won within horizon",
        "negative": "no won expansion after horizon",
        "censor": "horizon not elapsed",
        "split": "Temporal 70/15/15 by as_of. One customer per split.",
        "baseline": "expansion rules-v1",
        "forbidden": ["expansion_won_at", "final_expansion_amount"],
    },
    "PRODUCT_AFFINITY": {
        "name": "Product affinity",
        "entity_type": "customer",
        "horizon": 180,
        "label": "Customer adopted a recommended adjacent product.",
        "positive": "whitespace cell converted or expansion for that product won",
        "negative": "no adoption after horizon",
        "censor": "horizon not elapsed",
        "split": "Temporal 70/15/15 by as_of. Entity = customer.",
        "baseline": "whitespace propensity",
        "forbidden": ["final_product_set"],
    },
    "CUSTOMER_LIFETIME_VALUE": {
        "name": "Customer lifetime value",
        "entity_type": "customer",
        "horizon": 365,
        "label": "Observed realized revenue over the horizon (regression).",
        "positive": "realized ARR/expansion over horizon (numeric, not a class)",
        "negative": "n/a — regression; censored if horizon incomplete",
        "censor": "customer younger than horizon",
        "split": "Temporal 70/15/15 by as_of. One customer per split.",
        "baseline": "current ARR",
        "forbidden": ["final_ltv", "lifetime_revenue"],
    },
    "FORECAST_CALIBRATION": {
        "name": "Forecast calibration",
        "entity_type": "forecast",
        "horizon": 31,
        "label": "Period snapshot vs actual closed revenue.",
        "positive": "n/a — calibration residual, not a class",
        "negative": "n/a",
        "censor": "period not closed",
        "split": "Calendar months: train earlier months, validate next, test last.",
        "baseline": "rules-v1 weighted pipeline",
        "forbidden": ["actual_closed_revenue"],
    },
}

FEATURE_DEFINITIONS: dict[str, list[dict]] = {
    "LEAD_CONVERSION": [
        {
            "name": "lead_icp_score",
            "type": "int",
            "source": "lead_scores",
            "calculation": "latest LeadScore.icp_fit with created_at <= as_of",
            "window": "point",
            "null": 0,
            "freshness_hours": 24,
            "version": "v1",
        },
        {
            "name": "lead_intent_score",
            "type": "int",
            "source": "lead_scores",
            "calculation": "latest LeadScore.intent with created_at <= as_of",
            "window": "point",
            "null": 0,
            "freshness_hours": 24,
            "version": "v1",
        },
        {
            "name": "lead_engagement_score",
            "type": "int",
            "source": "lead_scores",
            "calculation": "latest LeadScore.engagement with created_at <= as_of",
            "window": "point",
            "null": 0,
            "freshness_hours": 24,
            "version": "v1",
        },
        {
            "name": "emails_last_30d",
            "type": "int",
            "source": "activities",
            "calculation": "count email activities in [as_of-30d, as_of]",
            "window": "30d",
            "null": 0,
            "freshness_hours": 24,
            "version": "v1",
        },
        {
            "name": "meetings_last_30d",
            "type": "int",
            "source": "meetings",
            "calculation": "count meetings in [as_of-30d, as_of]",
            "window": "30d",
            "null": 0,
            "freshness_hours": 24,
            "version": "v1",
        },
    ],
    "OPPORTUNITY_WIN": [
        {
            "name": "days_in_stage",
            "type": "int",
            "source": "opportunity_field_history",
            "calculation": "days since last stage change at or before as_of",
            "window": "point",
            "null": None,
            "freshness_hours": 1,
            "version": "v1",
        },
        {
            "name": "close_date_change_count",
            "type": "int",
            "source": "opportunity_field_history",
            "calculation": "count expected_close changes with changed_at <= as_of",
            "window": "lifetime_to_as_of",
            "null": 0,
            "freshness_hours": 1,
            "version": "v1",
        },
        {
            "name": "stage_probability",
            "type": "int",
            "source": "opportunity_field_history",
            "calculation": "probability as of T from history, else current if created_at <= as_of",
            "window": "point",
            "null": None,
            "freshness_hours": 1,
            "version": "v1",
        },
        {
            "name": "emails_last_30d",
            "type": "int",
            "source": "activities",
            "calculation": "count email activities in [as_of-30d, as_of]",
            "window": "30d",
            "null": 0,
            "freshness_hours": 24,
            "version": "v1",
        },
        {
            "name": "meetings_last_30d",
            "type": "int",
            "source": "meetings",
            "calculation": "count meetings in [as_of-30d, as_of]",
            "window": "30d",
            "null": 0,
            "freshness_hours": 24,
            "version": "v1",
        },
    ],
    "CUSTOMER_CHURN": [
        {
            "name": "customer_health_score",
            "type": "int",
            "source": "health_score_snapshots",
            "calculation": "latest snapshot.calculated_at <= as_of",
            "window": "point",
            "null": None,
            "freshness_hours": 24,
            "version": "v1",
        },
        {
            "name": "usage_30d_change",
            "type": "int",
            "source": "usage_rollups",
            "calculation": "trend_30d mapped to -1/0/1 using period_start <= as_of",
            "window": "30d",
            "null": None,
            "freshness_hours": 72,
            "version": "v1",
        },
        {
            "name": "critical_support_tickets",
            "type": "int",
            "source": "support_snapshots",
            "calculation": "open critical tickets with observed_at <= as_of",
            "window": "point",
            "null": 0,
            "freshness_hours": 168,
            "version": "v1",
        },
        {
            "name": "days_past_due",
            "type": "int",
            "source": "finance_snapshots",
            "calculation": "days past due from latest finance snapshot observed_at <= as_of",
            "window": "point",
            "null": 0,
            "freshness_hours": 168,
            "version": "v1",
        },
    ],
}

FEATURE_DEFINITIONS["CLOSE_DATE_SLIPPAGE"] = FEATURE_DEFINITIONS["OPPORTUNITY_WIN"]
FEATURE_DEFINITIONS["CUSTOMER_RENEWAL"] = FEATURE_DEFINITIONS["CUSTOMER_CHURN"]
FEATURE_DEFINITIONS["EXPANSION_PROPENSITY"] = FEATURE_DEFINITIONS["CUSTOMER_CHURN"]
FEATURE_DEFINITIONS["PRODUCT_AFFINITY"] = FEATURE_DEFINITIONS["CUSTOMER_CHURN"]
FEATURE_DEFINITIONS["CUSTOMER_LIFETIME_VALUE"] = FEATURE_DEFINITIONS["CUSTOMER_CHURN"]
FEATURE_DEFINITIONS["FORECAST_CALIBRATION"] = [
    {
        "name": "weighted_pipeline",
        "type": "float",
        "source": "forecast_snapshots",
        "calculation": "weighted value of snapshot created_at <= as_of",
        "window": "point",
        "null": None,
        "freshness_hours": 24,
        "version": "v1",
    }
]


def forbidden_features(task_key: str) -> set[str]:
    spec = TASKS.get(task_key) or {}
    return set(spec.get("forbidden") or [])


def ensure_catalog(db: Session, *, tenant_id: UUID, actor_id: UUID | None) -> list[PredictionTask]:
    settings = get_settings()
    rows: list[PredictionTask] = []
    for key, spec in TASKS.items():
        row = db.scalar(
            select(PredictionTask).where(
                PredictionTask.tenant_id == tenant_id,
                PredictionTask.task_key == key,
                PredictionTask.deleted_at.is_(None),
            )
        )
        if row is None:
            row = PredictionTask(
                tenant_id=tenant_id,
                created_by=actor_id,
                task_key=key,
                name=spec["name"],
                entity_type=spec["entity_type"],
                label_definition=spec["label"],
                prediction_horizon_days=spec["horizon"],
                feature_set_version="v1",
                label_version="v1",
                minimum_history_days=settings.ml_min_history_days,
                minimum_positive_labels=settings.ml_min_positive,
                minimum_negative_labels=settings.ml_min_negative,
                minimum_rows=settings.ml_min_rows,
                status="DATA_COLLECTION",
                split_policy=spec["split"],
            )
            db.add(row)
            db.flush()
        fs = db.scalar(
            select(FeatureSet).where(
                FeatureSet.tenant_id == tenant_id,
                FeatureSet.task_key == key,
                FeatureSet.feature_set_version == "v1",
                FeatureSet.deleted_at.is_(None),
            )
        )
        if fs is None:
            db.add(
                FeatureSet(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    task_key=key,
                    feature_set_version="v1",
                    definitions_json=json.dumps(FEATURE_DEFINITIONS.get(key, []), default=str),
                    status="active",
                )
            )
        label = db.scalar(
            select(LabelDefinition).where(
                LabelDefinition.tenant_id == tenant_id,
                LabelDefinition.task_key == key,
                LabelDefinition.label_version == "v1",
                LabelDefinition.deleted_at.is_(None),
            )
        )
        if label is None:
            db.add(
                LabelDefinition(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    task_key=key,
                    label_version="v1",
                    definition=spec["label"],
                    horizon_days=spec["horizon"],
                    positive_condition=spec["positive"],
                    negative_condition=spec["negative"],
                    censoring_rule=spec["censor"],
                )
            )
        champion = db.scalar(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id,
                ModelVersion.task_key == key,
                ModelVersion.is_rules == 1,
                ModelVersion.deleted_at.is_(None),
            )
        )
        if champion is None:
            db.add(
                ModelVersion(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    task_key=key,
                    version="rules-champion",
                    algorithm="rules",
                    status="CHAMPION",
                    is_rules=1,
                    metrics_json=None,
                )
            )
        rows.append(row)
    db.flush()
    return rows
