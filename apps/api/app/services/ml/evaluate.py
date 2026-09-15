from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ml import ModelEvaluation, ModelVersion, Prediction
from app.services.ml.catalog import TASKS
from app.services.ml.labels import resolve_label, upsert_outcome
from app.services.ml.timeutil import aware_dt, now_utc
from app.services.provider_metrics import MODEL_EVALUATION_TOTAL


def evaluate_matured(db: Session, *, tenant_id: UUID, actor_id: UUID | None = None) -> int:
    rows = list(
        db.scalars(
            select(Prediction).where(Prediction.tenant_id == tenant_id, Prediction.deleted_at.is_(None))
        ).all()
    )
    linked = 0
    for prediction in rows:
        if prediction.task_key not in TASKS:
            continue
        existing = db.scalar(
            select(ModelEvaluation).where(
                ModelEvaluation.tenant_id == tenant_id,
                ModelEvaluation.prediction_id == prediction.id,
                ModelEvaluation.deleted_at.is_(None),
            )
        )
        as_of = aware_dt(prediction.prediction_for) or aware_dt(prediction.created_at) or now_utc()
        resolved = resolve_label(
            db,
            tenant_id=tenant_id,
            task_key=prediction.task_key,
            entity_type=prediction.entity_type,
            entity_id=prediction.entity_id,
            as_of=as_of,
        )
        if resolved.status not in {"POSITIVE", "NEGATIVE"}:
            continue
        label = upsert_outcome(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            task_key=prediction.task_key,
            entity_type=prediction.entity_type,
            entity_id=prediction.entity_id,
            resolved=resolved,
            feature_snapshot_id=prediction.feature_snapshot_id,
        )
        predicted_pos = prediction.prediction == "positive" or (prediction.probability or 0) >= 0.5
        actual_pos = resolved.status == "POSITIVE"
        correct = 1 if predicted_pos == actual_pos else 0
        metrics = {
            "correct": correct,
            "predicted": prediction.prediction,
            "actual": resolved.status,
            "probability": float(prediction.probability or 0),
            "brier": round((float(prediction.probability or 0) - (1 if actual_pos else 0)) ** 2, 4),
        }
        if existing is None:
            existing = ModelEvaluation(
                tenant_id=tenant_id,
                created_by=actor_id,
                task_key=prediction.task_key,
                model_version_id=prediction.model_version_id,
                prediction_id=prediction.id,
            )
            db.add(existing)
        existing.outcome_label_id = label.id
        existing.correct = correct
        existing.metrics_json = json.dumps(metrics)
        existing.evaluated_at = now_utc()
        MODEL_EVALUATION_TOTAL.labels(task_key=prediction.task_key).inc()
        linked += 1
    if linked:
        db.flush()
    return linked


def task_metrics(db: Session, tenant_id: UUID, model_version_id: UUID) -> dict:
    rows = list(
        db.scalars(
            select(ModelEvaluation).where(
                ModelEvaluation.tenant_id == tenant_id,
                ModelEvaluation.model_version_id == model_version_id,
                ModelEvaluation.deleted_at.is_(None),
            )
        ).all()
    )
    if not rows:
        return {}
    correct = sum(row.correct or 0 for row in rows)
    return {
        "evaluated": len(rows),
        "accuracy": round(correct / len(rows), 4) if rows else None,
        "note": "Accuracy is reported with class counts. Do not treat it as the optimization target.",
    }


def list_models(db: Session, tenant_id: UUID) -> list[ModelVersion]:
    return list(
        db.scalars(
            select(ModelVersion)
            .where(ModelVersion.tenant_id == tenant_id, ModelVersion.deleted_at.is_(None))
            .order_by(ModelVersion.task_key, ModelVersion.created_at.desc())
        ).all()
    )
