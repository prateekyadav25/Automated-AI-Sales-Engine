from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.autonomy import AutonomousRun, EntityAutomationState


def get_state(db: Session, *, tenant_id: UUID, entity_type: str, entity_id: str) -> EntityAutomationState | None:
    return db.scalar(
        select(EntityAutomationState).where(
            EntityAutomationState.tenant_id == tenant_id,
            EntityAutomationState.entity_type == entity_type,
            EntityAutomationState.entity_id == str(entity_id),
            EntityAutomationState.deleted_at.is_(None),
        )
    )


def upsert_state(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    entity_type: str,
    entity_id: str,
    state: str,
    last_action: str = "",
    next_action: str = "",
    blocked_reason: str = "",
    run_id: UUID | None = None,
    paused_at: datetime | None | object = ...,
) -> EntityAutomationState:
    row = get_state(db, tenant_id=tenant_id, entity_type=entity_type, entity_id=str(entity_id))
    if row is None:
        row = EntityAutomationState(
            tenant_id=tenant_id,
            created_by=actor_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            state=state,
            last_action=last_action,
            next_action=next_action,
            blocked_reason=blocked_reason,
            run_id=run_id,
        )
        db.add(row)
        db.flush()
        return row
    row.state = state
    if last_action:
        row.last_action = last_action
    row.next_action = next_action
    row.blocked_reason = blocked_reason
    if run_id is not None:
        row.run_id = run_id
    if paused_at is not ...:
        row.paused_at = paused_at  # type: ignore[assignment]
    row.updated_by = actor_id
    return row


def is_entity_paused(db: Session, *, tenant_id: UUID, entity_type: str, entity_id: str) -> bool:
    row = get_state(db, tenant_id=tenant_id, entity_type=entity_type, entity_id=str(entity_id))
    return bool(row and row.paused_at is not None)


def pause_entity(db: Session, *, tenant_id: UUID, actor_id: UUID | None, entity_type: str, entity_id: str) -> EntityAutomationState:
    row = get_state(db, tenant_id=tenant_id, entity_type=entity_type, entity_id=str(entity_id))
    now = datetime.now(UTC)
    if row is None:
        return upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            state="PAUSED",
            last_action="pause",
            next_action="",
            blocked_reason="Paused by human",
            paused_at=now,
        )
    row.paused_at = now
    row.state = "PAUSED"
    row.last_action = "pause"
    row.next_action = ""
    row.blocked_reason = "Paused by human"
    row.updated_by = actor_id
    return row


def resume_entity(db: Session, *, tenant_id: UUID, actor_id: UUID | None, entity_type: str, entity_id: str) -> EntityAutomationState:
    row = get_state(db, tenant_id=tenant_id, entity_type=entity_type, entity_id=str(entity_id))
    if row is None:
        return upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            state="DISCOVERED",
            last_action="resume",
            next_action="enrich",
            blocked_reason="",
            paused_at=None,
        )
    row.paused_at = None
    if row.state == "PAUSED":
        row.state = "DISCOVERED"
    row.last_action = "resume"
    row.blocked_reason = ""
    row.next_action = row.next_action or "enrich"
    row.updated_by = actor_id
    return row


def latest_run_for(db: Session, *, tenant_id: UUID, run_id: UUID | None) -> AutonomousRun | None:
    if run_id is None:
        return None
    return db.scalar(
        select(AutonomousRun).where(
            AutonomousRun.tenant_id == tenant_id,
            AutonomousRun.id == run_id,
            AutonomousRun.deleted_at.is_(None),
        )
    )
