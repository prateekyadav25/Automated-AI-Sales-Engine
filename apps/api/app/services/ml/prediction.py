from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Lead, Opportunity, Renewal
from app.models.lifecycle import HealthScore
from app.models.ml import ModelVersion, Prediction
from app.models.post_sale import CustomerRisk
from app.models.signals import MLFeatureSnapshot
from app.services.audit import write_audit
from app.services.ml.catalog import TASKS
from app.services.ml.features import compute_features
from app.services.ml.snapshots import record_feature_snapshot
from app.services.ml.timeutil import now_utc
from app.services.provider_metrics import PREDICTIONS_TOTAL, SHADOW_PREDICTIONS_TOTAL
from app.services.qualification import latest_score


@dataclass
class PredictionResult:
    prediction: str
    probability: float
    confidence: int
    model_version: str
    provider_key: str
    feature_snapshot_id: UUID | None
    explanation: dict
    execution_mode: str


class PredictionProvider(Protocol):
    provider_key: str

    def predict(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        task_key: str,
        entity_type: str,
        entity_id: str,
        as_of: datetime | None = None,
    ) -> PredictionResult: ...


class RulesPredictionProvider:
    provider_key = "rules"

    def predict(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        task_key: str,
        entity_type: str,
        entity_id: str,
        as_of: datetime | None = None,
    ) -> PredictionResult:
        _ = as_of
        probability = 0.0
        confidence = 60
        explanation: dict = {"algorithm": "rules"}
        if task_key == "LEAD_CONVERSION":
            lead = db.get(Lead, UUID(entity_id))
            score = latest_score(db, lead) if lead else None
            probability = (score.total / 100) if score else 0.0
            confidence = score.confidence if score else 50
            explanation["baseline"] = "rules-v1 score threshold"
            explanation["score"] = score.total if score else 0
        elif task_key == "OPPORTUNITY_WIN":
            opp = db.get(Opportunity, UUID(entity_id))
            probability = (opp.probability / 100) if opp else 0.0
            explanation["baseline"] = "stage-weighted probability"
        elif task_key == "CUSTOMER_CHURN":
            risks = (
                db.scalars(
                    select(CustomerRisk).where(
                        CustomerRisk.tenant_id == tenant_id,
                        CustomerRisk.customer_id == UUID(entity_id),
                        CustomerRisk.status == "open",
                    )
                ).all()
                if entity_type == "customer"
                else []
            )
            high = sum(1 for row in risks if row.severity in {"high", "critical"})
            probability = min(0.95, 0.2 + 0.15 * high)
            explanation["baseline"] = "rules-v2 customer risk"
        elif task_key == "CUSTOMER_RENEWAL":
            renewal = db.scalar(
                select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.customer_id == UUID(entity_id), Renewal.deleted_at.is_(None))
            )
            probability = (renewal.readiness / 100) if renewal else 0.0
            explanation["baseline"] = "renewal readiness rules"
        else:
            health = db.scalar(
                select(HealthScore).where(HealthScore.tenant_id == tenant_id, HealthScore.customer_id == UUID(entity_id), HealthScore.deleted_at.is_(None))
            ) if entity_type == "customer" else None
            probability = (health.total / 100) if health else 0.0
            explanation["baseline"] = TASKS.get(task_key, {}).get("baseline", "rules")
        return PredictionResult(
            prediction="positive" if probability >= 0.5 else "negative",
            probability=round(float(probability), 4),
            confidence=confidence,
            model_version="rules-champion",
            provider_key="rules",
            feature_snapshot_id=None,
            explanation=explanation,
            execution_mode="ADVISORY",
        )


class ConstantPredictionProvider:
    provider_key = "constant"

    def __init__(self, probability: float, version: str):
        self.probability = probability
        self.version = version

    def predict(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        task_key: str,
        entity_type: str,
        entity_id: str,
        as_of: datetime | None = None,
    ) -> PredictionResult:
        _ = db, tenant_id, task_key, entity_type, entity_id, as_of
        return PredictionResult(
            prediction="positive" if self.probability >= 0.5 else "negative",
            probability=self.probability,
            confidence=int(self.probability * 100),
            model_version=self.version,
            provider_key="constant",
            feature_snapshot_id=None,
            explanation={"algorithm": "constant", "note": "Registered challenger stub, not a trained model"},
            execution_mode="SHADOW",
        )


def persist_prediction(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    task_key: str,
    entity_type: str,
    entity_id: str,
    result: PredictionResult,
    snapshot: MLFeatureSnapshot | None,
    execution_mode: str,
    model_version_id: UUID | None = None,
    prediction_for: datetime | None = None,
) -> Prediction:
    if execution_mode == "ACTIVE" and result.provider_key != "rules":
        raise ValueError("ML predictions cannot be ACTIVE")
    row = Prediction(
        tenant_id=tenant_id,
        created_by=actor_id,
        task_key=task_key,
        entity_type=entity_type,
        entity_id=entity_id,
        model_version_id=model_version_id,
        model_version=result.model_version,
        feature_snapshot_id=snapshot.id if snapshot else result.feature_snapshot_id,
        prediction=result.prediction,
        probability=result.probability,
        confidence=result.confidence,
        prediction_for=prediction_for or now_utc(),
        execution_mode=execution_mode,
        explanation_json=json.dumps(result.explanation, default=str),
        provider_key=result.provider_key,
    )
    db.add(row)
    db.flush()
    PREDICTIONS_TOTAL.labels(task_key=task_key, mode=execution_mode).inc()
    if execution_mode == "SHADOW":
        SHADOW_PREDICTIONS_TOTAL.labels(task_key=task_key).inc()
    return row


def get_challenger(db: Session, tenant_id: UUID, task_key: str) -> ModelVersion | None:
    return db.scalar(
        select(ModelVersion).where(
            ModelVersion.tenant_id == tenant_id,
            ModelVersion.task_key == task_key,
            ModelVersion.status == "CHALLENGER",
            ModelVersion.deleted_at.is_(None),
        )
    )


def maybe_shadow(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    task_key: str,
    entity_type: str,
    entity_id: str,
    snapshot: MLFeatureSnapshot | None = None,
) -> Prediction | None:
    challenger = get_challenger(db, tenant_id, task_key)
    if challenger is None:
        return None
    if challenger.algorithm != "constant":
        return None
    try:
        params = json.loads(challenger.package_versions or "{}")
    except json.JSONDecodeError:
        params = {}
    probability = float(params.get("probability", 0.5))
    provider = ConstantPredictionProvider(probability, challenger.version)
    result = provider.predict(
        db, tenant_id=tenant_id, task_key=task_key, entity_type=entity_type, entity_id=entity_id
    )
    return persist_prediction(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        task_key=task_key,
        entity_type=entity_type,
        entity_id=entity_id,
        result=result,
        snapshot=snapshot,
        execution_mode="SHADOW",
        model_version_id=challenger.id,
    )


def score_and_snapshot(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    task_key: str,
    entity_type: str,
    entity_id: str,
    customer_id: UUID | None = None,
    ruleset_version: str = "rules-v1",
) -> tuple[PredictionResult, MLFeatureSnapshot]:
    computed = compute_features(
        db, tenant_id=tenant_id, task_key=task_key, entity_type=entity_type, entity_id=entity_id
    )
    snapshot = record_feature_snapshot(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        customer_id=customer_id,
        entity_type=entity_type,
        entity_id=entity_id,
        task_key=task_key,
        features=computed.features,
        source_versions=computed.source_versions,
        ruleset_version=ruleset_version,
    )
    result = RulesPredictionProvider().predict(
        db, tenant_id=tenant_id, task_key=task_key, entity_type=entity_type, entity_id=entity_id
    )
    result.feature_snapshot_id = snapshot.id
    maybe_shadow(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        task_key=task_key,
        entity_type=entity_type,
        entity_id=entity_id,
        snapshot=snapshot,
    )
    return result, snapshot


def latest_shadow(db: Session, tenant_id: UUID, task_key: str, entity_type: str, entity_id: str) -> Prediction | None:
    return db.scalar(
        select(Prediction)
        .where(
            Prediction.tenant_id == tenant_id,
            Prediction.task_key == task_key,
            Prediction.entity_type == entity_type,
            Prediction.entity_id == entity_id,
            Prediction.execution_mode == "SHADOW",
            Prediction.deleted_at.is_(None),
        )
        .order_by(Prediction.created_at.desc())
    )


def assert_no_ml_action(execution_mode: str, provider_key: str) -> None:
    if provider_key != "rules" and execution_mode == "ACTIVE":
        raise ValueError("ML must not drive external actions")


def record_mode_change(db: Session, *, tenant_id: UUID, actor_id: UUID | None, model_id: UUID, mode: str) -> None:
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="ml.prediction_mode",
        entity_type="model_version",
        entity_id=str(model_id),
        after={"execution_mode": mode},
    )
