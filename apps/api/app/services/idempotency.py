from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.autonomy import AutomationIdempotencyKey


def claim_key(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    key: str,
    workflow: str = "",
    entity_id: str = "",
    action_type: str = "",
    window: str = "",
    result_ref: str = "",
) -> tuple[bool, AutomationIdempotencyKey]:
    existing = db.scalar(
        select(AutomationIdempotencyKey).where(
            AutomationIdempotencyKey.tenant_id == tenant_id,
            AutomationIdempotencyKey.key == key,
            AutomationIdempotencyKey.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return False, existing
    row = AutomationIdempotencyKey(
        tenant_id=tenant_id,
        created_by=actor_id,
        key=key,
        workflow=workflow,
        entity_id=entity_id,
        action_type=action_type,
        window=window,
        result_ref=result_ref,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        recovered = db.scalar(
            select(AutomationIdempotencyKey).where(
                AutomationIdempotencyKey.tenant_id == tenant_id,
                AutomationIdempotencyKey.key == key,
                AutomationIdempotencyKey.deleted_at.is_(None),
            )
        )
        if recovered is None:
            raise
        return False, recovered
    return True, row


def remember_result(row: AutomationIdempotencyKey, result_ref: str) -> None:
    row.result_ref = result_ref


def lock_row(db: Session, model, tenant_id: UUID, row_id: UUID):
    stmt = select(model).where(model.id == row_id, model.tenant_id == tenant_id, model.deleted_at.is_(None))
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def claim_daily_slot(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    kind: str,
    limit: int,
) -> bool:
    if limit <= 0:
        return True
    day = datetime.now(UTC).date().isoformat()
    for slot in range(1, limit + 1):
        claimed, _ = claim_key(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            key=f"cap:{kind}:{tenant_id}:{day}:{slot}",
            workflow="daily_cap",
            action_type=kind,
            window=day,
        )
        if claimed:
            return True
    return False
