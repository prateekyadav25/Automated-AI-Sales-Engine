from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.autonomy import AutopilotSettings
from app.models.pilot import AutopilotSettingsVersion
from app.services.audit import write_audit


def snapshot_settings(settings: AutopilotSettings) -> dict:
    skip = {"id", "tenant_id", "created_by", "updated_by", "created_at", "updated_at", "deleted_at"}
    payload = {}
    for key, value in settings.__dict__.items():
        if key.startswith("_") or key in skip:
            continue
        payload[key] = str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
    return payload


def record_settings_version(
    db: Session,
    *,
    settings: AutopilotSettings,
    actor_id: UUID | None,
    reason: str,
) -> AutopilotSettingsVersion:
    next_version = int(settings.current_policy_version or 1) + 1
    settings.current_policy_version = next_version
    row = AutopilotSettingsVersion(
        tenant_id=settings.tenant_id,
        created_by=actor_id,
        version=next_version,
        snapshot_json=json.dumps(snapshot_settings(settings), default=str),
        reason=reason,
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        tenant_id=settings.tenant_id,
        actor_id=actor_id,
        action="autonomy.settings.version",
        entity_type="autopilot_settings_version",
        entity_id=str(row.id),
        after={"version": next_version, "reason": reason},
    )
    return row


def current_policy_version(db: Session, tenant_id: UUID) -> int:
    row = db.scalar(select(AutopilotSettings).where(AutopilotSettings.tenant_id == tenant_id, AutopilotSettings.deleted_at.is_(None)))
    return int(row.current_policy_version) if row else 1
