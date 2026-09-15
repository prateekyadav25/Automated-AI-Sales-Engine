from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ml import DatasetVersion, TrainingExample
from app.models.signals import MLFeatureSnapshot
from app.providers.object_storage import dataset_object_key, get_object_storage
from app.services.audit import write_audit
from app.services.ml.catalog import TASKS, forbidden_features
from app.services.ml.labels import resolve_label, upsert_outcome
from app.services.ml.timeutil import aware_dt, now_utc, truncate_seconds
from app.services.provider_metrics import DATASET_BUILD_FAILURE, DATASET_BUILD_TOTAL


class DatasetBuildError(ValueError):
    pass


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def validate_snapshot(snapshot: MLFeatureSnapshot, task_key: str) -> None:
    try:
        features = json.loads(snapshot.features_json or "{}")
        sources = json.loads(snapshot.source_versions_json or "{}")
    except json.JSONDecodeError as exc:
        raise DatasetBuildError("Invalid snapshot JSON") from exc
    leak = forbidden_features(task_key).intersection(features)
    if leak:
        raise DatasetBuildError(f"Forbidden leakage features: {sorted(leak)}")
    as_of = aware_dt(snapshot.as_of)
    if as_of is None:
        raise DatasetBuildError("Snapshot missing as_of")
    for name, meta in sources.items():
        observed = _parse_iso((meta or {}).get("max_observed_at") if isinstance(meta, dict) else None)
        if observed and observed > as_of:
            raise DatasetBuildError(f"Feature {name} observed after prediction time")
    if snapshot.task_key and snapshot.task_key != task_key:
        raise DatasetBuildError("Snapshot task_key does not match dataset task")


def _fingerprint(rows: list[tuple]) -> str:
    payload = json.dumps(rows, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _assign_splits(examples: list[TrainingExample]) -> None:
    by_entity: dict[str, list[TrainingExample]] = {}
    for row in examples:
        by_entity.setdefault(row.entity_id, []).append(row)
    ordered = sorted(by_entity.items(), key=lambda item: min((aware_dt(r.prediction_as_of) or now_utc() for r in item[1])))
    count = len(ordered)
    train_end = max(1, int(count * 0.70)) if count else 0
    val_end = max(train_end, int(count * 0.85)) if count else 0
    for index, (_entity, rows) in enumerate(ordered):
        if index < train_end:
            split = "train"
        elif index < val_end:
            split = "validation"
        else:
            split = "test"
        if count < 3:
            split = "train"
        for row in rows:
            row.split = split


def quality_report(examples: list[TrainingExample], snapshots: dict[UUID, MLFeatureSnapshot]) -> dict:
    missing = 0
    fields = 0
    for row in examples:
        snap = snapshots.get(row.feature_snapshot_id)
        if snap is None:
            continue
        features = json.loads(snap.features_json or "{}")
        fields += max(len(features), 1)
        missing += sum(1 for value in features.values() if value is None)
    missingness = (missing / fields) if fields else 0.0
    statuses = [row.label_status for row in examples]
    return {
        "missingness": round(missingness, 4),
        "duplicate_rate": 0.0,
        "invalid_features": 0,
        "label_distribution": {
            "POSITIVE": statuses.count("POSITIVE"),
            "NEGATIVE": statuses.count("NEGATIVE"),
            "PENDING": statuses.count("PENDING"),
            "CENSORED": statuses.count("CENSORED"),
        },
        "coverage": len(examples),
    }


def next_dataset_version(db: Session, tenant_id: UUID, task_key: str) -> str:
    count = (
        db.scalar(
            select(func.count()).where(
                DatasetVersion.tenant_id == tenant_id,
                DatasetVersion.task_key == task_key,
                DatasetVersion.deleted_at.is_(None),
            )
        )
        or 0
    )
    return f"ds-{int(count) + 1:04d}"


def build_dataset(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    task_key: str,
    feature_set_version: str = "v1",
    label_version: str = "v1",
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    scope: str = "TENANT_LOCAL",
) -> DatasetVersion:
    if task_key not in TASKS:
        raise DatasetBuildError(f"Unknown task {task_key}")
    if scope != "TENANT_LOCAL":
        raise DatasetBuildError("Only TENANT_LOCAL datasets are allowed")
    settings = get_settings()
    end = truncate_seconds(date_end or now_utc())
    start = truncate_seconds(date_start or datetime.fromisoformat("1970-01-01T00:00:00+00:00"))
    snapshots = list(
        db.scalars(
            select(MLFeatureSnapshot).where(
                MLFeatureSnapshot.tenant_id == tenant_id,
                MLFeatureSnapshot.task_key == task_key,
                MLFeatureSnapshot.feature_set_version == feature_set_version,
                MLFeatureSnapshot.deleted_at.is_(None),
                MLFeatureSnapshot.as_of >= start,
                MLFeatureSnapshot.as_of <= end,
            )
        ).all()
    )
    try:
        examples: list[TrainingExample] = []
        fingerprint_rows: list[tuple] = []
        snap_map: dict[UUID, MLFeatureSnapshot] = {}
        for snap in snapshots:
            validate_snapshot(snap, task_key)
            as_of = aware_dt(snap.as_of)
            if as_of is None:
                raise DatasetBuildError("Snapshot missing as_of")
            resolved = resolve_label(
                db,
                tenant_id=tenant_id,
                task_key=task_key,
                entity_type=snap.entity_type,
                entity_id=snap.entity_id,
                as_of=as_of,
            )
            upsert_outcome(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                task_key=task_key,
                entity_type=snap.entity_type,
                entity_id=snap.entity_id,
                resolved=resolved,
                feature_snapshot_id=snap.id,
                label_version=label_version,
            )
            features = json.loads(snap.features_json or "{}")
            features_hash = hashlib.sha256(json.dumps(features, sort_keys=True, default=str).encode()).hexdigest()
            example = TrainingExample(
                tenant_id=tenant_id,
                created_by=actor_id,
                task_key=task_key,
                entity_type=snap.entity_type,
                entity_id=snap.entity_id,
                prediction_as_of=as_of,
                feature_snapshot_id=snap.id,
                label=resolved.value,
                label_status=resolved.status,
                label_observed_at=resolved.occurred_at,
                feature_set_version=feature_set_version,
                label_version=label_version,
            )
            examples.append(example)
            snap_map[snap.id] = snap
            fingerprint_rows.append(
                (snap.entity_id, as_of.isoformat(), feature_set_version, label_version, resolved.status, resolved.value, features_hash)
            )
        _assign_splits(examples)
        quality = quality_report(examples, snap_map)
        if quality["missingness"] > settings.ml_max_missingness:
            raise DatasetBuildError(f"Missingness {quality['missingness']} exceeds {settings.ml_max_missingness}")
        fingerprint_rows.sort()
        digest = _fingerprint(fingerprint_rows)
        existing = db.scalar(
            select(DatasetVersion).where(
                DatasetVersion.tenant_id == tenant_id,
                DatasetVersion.task_key == task_key,
                DatasetVersion.fingerprint == digest,
                DatasetVersion.deleted_at.is_(None),
            )
        )
        version = existing.version if existing else next_dataset_version(db, tenant_id, task_key)
        pos = sum(1 for row in examples if row.label_status == "POSITIVE")
        neg = sum(1 for row in examples if row.label_status == "NEGATIVE")
        censored = sum(1 for row in examples if row.label_status in {"CENSORED", "PENDING"})
        row = existing or DatasetVersion(
            tenant_id=tenant_id,
            created_by=actor_id,
            task_key=task_key,
            version=version,
            feature_set_version=feature_set_version,
            label_version=label_version,
            scope="TENANT_LOCAL",
        )
        row.date_start = start
        row.date_end = end
        row.row_count = len(examples)
        row.positive_count = pos
        row.negative_count = neg
        row.censored_count = censored
        row.fingerprint = digest
        row.quality_json = json.dumps(quality, default=str)
        row.status = "built"
        if existing is None:
            db.add(row)
            db.flush()
        for example in examples:
            example.dataset_id = row.id
            db.add(example)
        db.flush()
        key = dataset_object_key(tenant_id=tenant_id, task_key=task_key, version=row.version)
        lines = []
        for example in examples:
            snap = snap_map[example.feature_snapshot_id]
            lines.append(
                json.dumps(
                    {
                        "entity_id": example.entity_id,
                        "as_of": aware_dt(example.prediction_as_of).isoformat() if example.prediction_as_of else None,
                        "label": example.label,
                        "label_status": example.label_status,
                        "split": example.split,
                        "features": json.loads(snap.features_json or "{}"),
                    },
                    default=str,
                )
            )
        get_object_storage().put(key, ("\n".join(lines) + "\n").encode(), content_type="application/jsonl")
        row.object_key = key
        write_audit(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="ml.dataset.create",
            entity_type="dataset_version",
            entity_id=str(row.id),
            after={"task_key": task_key, "version": row.version, "fingerprint": digest, "rows": row.row_count},
        )
        DATASET_BUILD_TOTAL.labels(task_key=task_key, status="ok").inc()
        return row
    except Exception:
        DATASET_BUILD_FAILURE.labels(task_key=task_key).inc()
        raise
