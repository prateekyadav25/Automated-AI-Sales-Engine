from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pilot import ReadinessNotification
from app.services.audit import write_audit


def notify_if_ready(db: Session, *, tenant_id: UUID, actor_id: UUID | None, report: dict) -> None:
    if report.get("recommended_status") != "READY_FOR_EXPERIMENT":
        return
    existing = db.scalar(
        select(ReadinessNotification).where(
            ReadinessNotification.tenant_id == tenant_id,
            ReadinessNotification.task_key == report["task_key"],
            ReadinessNotification.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return
    row = ReadinessNotification(
        tenant_id=tenant_id,
        created_by=actor_id,
        task_key=report["task_key"],
        previous_status=str(report.get("status") or "DATA_COLLECTION"),
        new_status="READY_FOR_EXPERIMENT",
        notified_at=datetime.now(UTC),
    )
    db.add(row)
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="ml.readiness.ready_for_experiment",
        entity_type="prediction_task",
        entity_id=report["task_key"],
        after={"status": "READY_FOR_EXPERIMENT", "trained": False},
    )
