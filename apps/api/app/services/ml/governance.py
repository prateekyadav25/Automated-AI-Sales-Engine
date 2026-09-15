from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ml import ModelVersion
from app.services.audit import write_audit

ALLOWED = {
    "EXPERIMENTAL": {"CANDIDATE", "RETIRED"},
    "CANDIDATE": {"CHALLENGER", "EXPERIMENTAL", "RETIRED"},
    "CHALLENGER": {"CANDIDATE", "CHAMPION", "RETIRED"},
    "CHAMPION": {"RETIRED", "CHALLENGER"},
    "RETIRED": set(),
}


class GovernanceError(ValueError):
    pass


def get_model(db: Session, tenant_id: UUID, model_id: UUID) -> ModelVersion:
    row = db.scalar(
        select(ModelVersion).where(
            ModelVersion.id == model_id,
            ModelVersion.tenant_id == tenant_id,
            ModelVersion.deleted_at.is_(None),
        )
    )
    if row is None:
        raise GovernanceError("Model version not found")
    return row


def promote(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    model_id: UUID,
    target: str,
    reason: str,
) -> ModelVersion:
    row = get_model(db, tenant_id, model_id)
    if target not in ALLOWED.get(row.status, set()):
        raise GovernanceError(f"Cannot promote {row.status} to {target}")
    if target == "CHAMPION" and row.is_rules != 1 and not get_settings().ml_allow_champion:
        raise GovernanceError("ML models cannot become CHAMPION in Batch 7")
    previous = row.status
    if target == "CHALLENGER":
        current = db.scalars(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id,
                ModelVersion.task_key == row.task_key,
                ModelVersion.status == "CHALLENGER",
                ModelVersion.id != row.id,
                ModelVersion.deleted_at.is_(None),
            )
        ).all()
        for other in current:
            other.status = "CANDIDATE"
    if target == "CHAMPION":
        champs = db.scalars(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id,
                ModelVersion.task_key == row.task_key,
                ModelVersion.status == "CHAMPION",
                ModelVersion.id != row.id,
                ModelVersion.deleted_at.is_(None),
            )
        ).all()
        for other in champs:
            other.status = "RETIRED"
    row.status = target
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="ml.promote",
        entity_type="model_version",
        entity_id=str(row.id),
        before={"status": previous},
        after={"status": target, "reason": reason, "metrics": row.metrics_json},
    )
    return row


def rollback_champion(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    task_key: str,
    reason: str,
) -> ModelVersion:
    current = db.scalar(
        select(ModelVersion).where(
            ModelVersion.tenant_id == tenant_id,
            ModelVersion.task_key == task_key,
            ModelVersion.status == "CHAMPION",
            ModelVersion.deleted_at.is_(None),
        )
    )
    previous = db.scalar(
        select(ModelVersion)
        .where(
            ModelVersion.tenant_id == tenant_id,
            ModelVersion.task_key == task_key,
            ModelVersion.status == "RETIRED",
            ModelVersion.deleted_at.is_(None),
        )
        .order_by(ModelVersion.updated_at.desc())
    )
    if previous is None:
        rules = db.scalar(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id,
                ModelVersion.task_key == task_key,
                ModelVersion.is_rules == 1,
                ModelVersion.deleted_at.is_(None),
            )
        )
        previous = rules
    if previous is None:
        raise GovernanceError("No previous champion to restore")
    if current and current.id != previous.id:
        current.status = "RETIRED"
    previous.status = "CHAMPION"
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="ml.rollback",
        entity_type="model_version",
        entity_id=str(previous.id),
        after={"task_key": task_key, "reason": reason, "restored": previous.version},
    )
    return previous
