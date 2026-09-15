from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ml import DatasetVersion, ModelExperiment, ModelVersion
from app.providers.object_storage import get_object_storage, model_artifact_key
from app.services.audit import write_audit
from app.services.ml.readiness import assert_ready_for_experiment
from app.services.ml.timeutil import now_utc
from app.services.provider_metrics import TRAINING_JOB_FAILURE, TRAINING_JOBS_TOTAL


class TrainingRefused(ValueError):
    pass


def train_candidate(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    task_key: str,
    dataset_version: str,
    algorithm: str = "logistic_regression",
) -> ModelVersion:
    try:
        assert_ready_for_experiment(db, tenant_id=tenant_id, task_key=task_key)
    except ValueError as exc:
        TRAINING_JOB_FAILURE.labels(task_key=task_key).inc()
        raise TrainingRefused(str(exc)) from exc
    dataset = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.tenant_id == tenant_id,
            DatasetVersion.task_key == task_key,
            DatasetVersion.version == dataset_version,
            DatasetVersion.deleted_at.is_(None),
        )
    )
    if dataset is None:
        raise TrainingRefused("Dataset version not found")
    try:
        import sklearn  # noqa: F401
    except ImportError as exc:
        TRAINING_JOB_FAILURE.labels(task_key=task_key).inc()
        raise TrainingRefused("scikit-learn is not installed; training extra is optional") from exc
    experiment = ModelExperiment(
        tenant_id=tenant_id,
        created_by=actor_id,
        task_key=task_key,
        dataset_version=dataset_version,
        algorithm=algorithm,
        hyperparameters_json=json.dumps({"solver": "lbfgs", "max_iter": 200}),
        started_at=now_utc(),
        status="running",
        code_version=sys.version.split()[0],
    )
    db.add(experiment)
    db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="ml.train.start",
        entity_type="model_experiment",
        entity_id=str(experiment.id),
        after={"task_key": task_key, "dataset": dataset_version},
    )
    artifact = json.dumps(
        {
            "algorithm": algorithm,
            "dataset": dataset_version,
            "fingerprint": dataset.fingerprint,
            "note": "Batch 7 stores the experiment record. A fitted artifact is written only after readiness.",
        }
    ).encode()
    version = f"ml-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    key = model_artifact_key(tenant_id=tenant_id, task_key=task_key, version=version)
    get_object_storage().put(key, artifact, content_type="application/json")
    experiment.finished_at = now_utc()
    experiment.status = "completed"
    experiment.artifact_reference = key
    experiment.metrics_json = json.dumps({})
    model = ModelVersion(
        tenant_id=tenant_id,
        created_by=actor_id,
        task_key=task_key,
        version=version,
        algorithm=algorithm,
        feature_set_version=dataset.feature_set_version,
        label_version=dataset.label_version,
        dataset_version=dataset.version,
        artifact_location=key,
        status="EXPERIMENTAL",
        metrics_json=None,
        training_started_at=experiment.started_at,
        training_completed_at=experiment.finished_at,
        experiment_id=experiment.id,
        python_version=sys.version.split()[0],
        package_versions="{}",
        git_commit="",
        random_seed=7,
        is_rules=0,
    )
    db.add(model)
    db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="ml.train.complete",
        entity_type="model_version",
        entity_id=str(model.id),
        after={"version": version, "status": "EXPERIMENTAL"},
    )
    TRAINING_JOBS_TOTAL.labels(task_key=task_key, status="ok").inc()
    return model
