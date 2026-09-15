from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.funnel import VoiceScript, VoiceScriptVersion
from app.services.audit import write_audit
from app.services.query import get_owned


def list_scripts(db: Session, tenant_id: UUID) -> list[VoiceScript]:
    return list(
        db.scalars(
            select(VoiceScript)
            .where(VoiceScript.tenant_id == tenant_id, VoiceScript.deleted_at.is_(None))
            .order_by(VoiceScript.created_at.desc())
        )
    )


def create_script(db: Session, *, tenant_id: UUID, actor_id: UUID, name: str, purpose: str = "outbound") -> VoiceScript:
    row = VoiceScript(tenant_id=tenant_id, created_by=actor_id, name=name.strip(), purpose=purpose, status="draft")
    db.add(row)
    db.flush()
    return row


def add_version(db: Session, *, tenant_id: UUID, actor_id: UUID, script: VoiceScript, body: str) -> VoiceScriptVersion:
    version = (script.current_version or 0) + 1
    row = VoiceScriptVersion(
        tenant_id=tenant_id,
        created_by=actor_id,
        script_id=script.id,
        version=version,
        body=body.strip(),
        status="draft",
    )
    db.add(row)
    script.current_version = version
    db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="voice.script_version",
        entity_type="voice_script",
        entity_id=str(script.id),
        after={"version": version},
    )
    return row


def publish_version(db: Session, *, tenant_id: UUID, actor_id: UUID, script_id: UUID, version_id: UUID) -> VoiceScript:
    script = get_owned(db, VoiceScript, tenant_id, script_id)
    version = get_owned(db, VoiceScriptVersion, tenant_id, version_id)
    if version.script_id != script.id:
        raise HTTPException(status_code=409, detail="Version does not belong to this script")
    for row in db.scalars(select(VoiceScriptVersion).where(VoiceScriptVersion.script_id == script.id)).all():
        row.status = "archived" if row.id != version.id and row.status == "published" else row.status
    version.status = "published"
    script.status = "published"
    script.current_version = version.version
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="voice.script_publish",
        entity_type="voice_script",
        entity_id=str(script.id),
        after={"version": version.version},
    )
    return script


def current_published_body(db: Session, tenant_id: UUID) -> tuple[str, UUID | None]:
    script = db.scalar(
        select(VoiceScript).where(
            VoiceScript.tenant_id == tenant_id,
            VoiceScript.status == "published",
            VoiceScript.deleted_at.is_(None),
        )
    )
    if script is None:
        return "", None
    version = db.scalar(
        select(VoiceScriptVersion).where(
            VoiceScriptVersion.tenant_id == tenant_id,
            VoiceScriptVersion.script_id == script.id,
            VoiceScriptVersion.status == "published",
            VoiceScriptVersion.deleted_at.is_(None),
        )
    )
    if version is None:
        return "", None
    return version.body, version.id
