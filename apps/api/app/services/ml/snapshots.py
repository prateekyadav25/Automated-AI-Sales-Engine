from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models.signals import MLFeatureSnapshot
from app.services.ml.timeutil import now_utc, truncate_seconds


class SnapshotImmutableError(ValueError):
    pass


def record_feature_snapshot(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    entity_type: str,
    entity_id: str,
    task_key: str,
    features: dict,
    source_versions: dict | None = None,
    feature_set_version: str = "v1",
    as_of: datetime | None = None,
    customer_id: UUID | None = None,
    ruleset_version: str = "rules-v2",
    correction_of_id: UUID | None = None,
) -> MLFeatureSnapshot:
    stamped = truncate_seconds(as_of or now_utc())
    existing = db.scalar(
        select(MLFeatureSnapshot).where(
            MLFeatureSnapshot.tenant_id == tenant_id,
            MLFeatureSnapshot.entity_type == entity_type,
            MLFeatureSnapshot.entity_id == entity_id,
            MLFeatureSnapshot.task_key == task_key,
            MLFeatureSnapshot.feature_set_version == feature_set_version,
            MLFeatureSnapshot.as_of == stamped,
            MLFeatureSnapshot.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing
    row = MLFeatureSnapshot(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer_id,
        entity_type=entity_type,
        entity_id=entity_id,
        task_key=task_key,
        feature_set_version=feature_set_version,
        as_of=stamped,
        features_json=json.dumps(features, default=str)[:16000],
        source_versions_json=json.dumps(source_versions or {}, default=str)[:8000],
        ruleset_version=ruleset_version,
        captured_at=now_utc(),
        immutable=True,
        correction_of_id=correction_of_id,
    )
    db.add(row)
    db.flush()
    return row


def assert_snapshot_immutable(row: MLFeatureSnapshot) -> None:
    if row.immutable:
        raise SnapshotImmutableError("Feature snapshots are immutable after creation")


def correct_snapshot(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    original: MLFeatureSnapshot,
    features: dict,
) -> MLFeatureSnapshot:
    return record_feature_snapshot(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type=original.entity_type,
        entity_id=original.entity_id,
        task_key=original.task_key,
        features=features,
        source_versions={"correction_of": str(original.id)},
        feature_set_version=original.feature_set_version,
        customer_id=original.customer_id,
        ruleset_version=original.ruleset_version,
        correction_of_id=original.id,
    )


@event.listens_for(MLFeatureSnapshot, "before_update")
def _deny_snapshot_update(_mapper, _connection, target: MLFeatureSnapshot) -> None:
    state = sa_inspect(target)
    protected = {"features_json", "as_of", "entity_id", "task_key", "feature_set_version", "entity_type"}
    if any(name in state.attrs and state.attrs[name].history.has_changes() for name in protected):
        raise SnapshotImmutableError("Feature snapshots are immutable after creation")


@event.listens_for(MLFeatureSnapshot, "before_delete")
def _deny_snapshot_delete(_mapper, _connection, target: MLFeatureSnapshot) -> None:
    assert_snapshot_immutable(target)
