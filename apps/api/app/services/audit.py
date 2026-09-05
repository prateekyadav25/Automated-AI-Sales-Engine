import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.identity import AuditLog, DomainEvent


def write_audit(
    db: Session,
    *,
    tenant_id: UUID | None,
    actor_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: str = "",
    before: Any = None,
    after: Any = None,
    actor_type: str = "human",
    ip: str | None = None,
    correlation_id: str = "",
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=None if before is None else json.dumps(before, default=str),
            after_json=None if after is None else json.dumps(after, default=str),
            ip=ip,
            correlation_id=correlation_id,
        )
    )


def emit_event(
    db: Session,
    *,
    tenant_id: UUID,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict | None = None,
    correlation_id: str = "",
) -> None:
    db.add(
        DomainEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_json=json.dumps(payload or {}, default=str),
            correlation_id=correlation_id,
        )
    )
