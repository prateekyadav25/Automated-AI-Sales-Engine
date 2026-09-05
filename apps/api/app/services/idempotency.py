from uuid import UUID

from sqlalchemy import select
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
    db.add(row)
    db.flush()
    return True, row


def remember_result(row: AutomationIdempotencyKey, result_ref: str) -> None:
    row.result_ref = result_ref
