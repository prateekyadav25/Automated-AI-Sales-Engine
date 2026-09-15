from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ml import PredictionTask
from app.models.signals import MLFeatureSnapshot, MLOutcomeLabel
from app.services.ml.catalog import TASKS, ensure_catalog
from app.services.ml.timeutil import aware_dt, now_utc
from app.services.readiness_notify import notify_if_ready


def _task(db: Session, tenant_id: UUID, task_key: str) -> PredictionTask:
    ensure_catalog(db, tenant_id=tenant_id, actor_id=None)
    row = db.scalar(
        select(PredictionTask).where(
            PredictionTask.tenant_id == tenant_id,
            PredictionTask.task_key == task_key,
            PredictionTask.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ValueError(f"Unknown task {task_key}")
    return row


def readiness_report(db: Session, *, tenant_id: UUID, task_key: str) -> dict:
    settings = get_settings()
    task = _task(db, tenant_id, task_key)
    snapshots = list(
        db.scalars(
            select(MLFeatureSnapshot).where(
                MLFeatureSnapshot.tenant_id == tenant_id,
                MLFeatureSnapshot.task_key == task_key,
                MLFeatureSnapshot.deleted_at.is_(None),
            )
        ).all()
    )
    labels = list(
        db.scalars(
            select(MLOutcomeLabel).where(
                MLOutcomeLabel.tenant_id == tenant_id,
                MLOutcomeLabel.task_key == task_key,
                MLOutcomeLabel.deleted_at.is_(None),
            )
        ).all()
    )
    pos = sum(1 for row in labels if row.label_status == "POSITIVE")
    neg = sum(1 for row in labels if row.label_status == "NEGATIVE")
    pending = sum(1 for row in labels if row.label_status == "PENDING")
    censored = sum(1 for row in labels if row.label_status == "CENSORED")
    mature = pos + neg
    times = [aware_dt(row.as_of) for row in snapshots if row.as_of]
    history_days = 0
    if times:
        history_days = max(0, (max(times) - min(times)).days)
    min_rows = max(task.minimum_rows, settings.ml_min_rows)
    min_pos = max(task.minimum_positive_labels, settings.ml_min_positive)
    min_neg = max(task.minimum_negative_labels, settings.ml_min_negative)
    min_hist = max(task.minimum_history_days, settings.ml_min_history_days)
    ready = len(snapshots) >= min_rows and pos >= min_pos and neg >= min_neg and history_days >= min_hist
    if ready:
        status = "READY_FOR_EXPERIMENT"
        reason = "Minimum rows, mature labels, and history are met."
    elif mature == 0:
        status = "DATA_COLLECTION"
        reason = "NOT ENOUGH MATURE LABELS"
    else:
        status = "DATA_COLLECTION"
        reason = "DATA COLLECTION"
    if task.status not in {"EXPERIMENTAL", "VALIDATED", "PRODUCTION", "RETIRED"}:
        task.status = status
    return {
        "task_key": task_key,
        "name": TASKS.get(task_key, {}).get("name", task.name),
        "entity_type": task.entity_type,
        "status": task.status,
        "recommended_status": status,
        "reason": reason,
        "rows": len(snapshots),
        "mature_labels": mature,
        "positive": pos,
        "negative": neg,
        "pending": pending,
        "censored": censored,
        "history_days": history_days,
        "minimum_rows": min_rows,
        "minimum_positive": min_pos,
        "minimum_negative": min_neg,
        "minimum_history_days": min_hist,
        "feature_set_version": task.feature_set_version,
        "label_version": task.label_version,
        "horizon_days": task.prediction_horizon_days,
        "baseline": TASKS.get(task_key, {}).get("baseline", ""),
        "split_policy": task.split_policy,
    }


def list_readiness(db: Session, *, tenant_id: UUID, actor_id: UUID | None = None) -> list[dict]:
    ensure_catalog(db, tenant_id=tenant_id, actor_id=None)
    rows = [readiness_report(db, tenant_id=tenant_id, task_key=key) for key in TASKS]
    for row in rows:
        notify_if_ready(db, tenant_id=tenant_id, actor_id=actor_id, report=row)
    return rows


def assert_ready_for_experiment(db: Session, *, tenant_id: UUID, task_key: str) -> dict:
    report = readiness_report(db, tenant_id=tenant_id, task_key=task_key)
    if report["recommended_status"] != "READY_FOR_EXPERIMENT":
        raise ValueError(f"{task_key} is not READY_FOR_EXPERIMENT: {report['reason']}")
    return report


def recent_enough(as_of, hours: int) -> bool:
    stamped = aware_dt(as_of)
    if stamped is None:
        return False
    return now_utc() - stamped <= timedelta(hours=hours)


def snapshot_count(db: Session, tenant_id: UUID) -> int:
    return int(db.scalar(select(func.count()).select_from(MLFeatureSnapshot).where(MLFeatureSnapshot.tenant_id == tenant_id)) or 0)
