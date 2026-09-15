import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.post_sale import AIArtifact


def fingerprint(payload: object) -> str:
    blob = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get_artifact(db: Session, *, tenant_id: UUID, kind: str, entity_type: str, entity_id: str) -> AIArtifact | None:
    return db.scalar(
        select(AIArtifact).where(
            AIArtifact.tenant_id == tenant_id,
            AIArtifact.kind == kind,
            AIArtifact.entity_type == entity_type,
            AIArtifact.entity_id == entity_id,
            AIArtifact.deleted_at.is_(None),
        )
    )


def reuse_or_none(db: Session, *, tenant_id: UUID, kind: str, entity_type: str, entity_id: str, source_fingerprint: str) -> AIArtifact | None:
    row = get_artifact(db, tenant_id=tenant_id, kind=kind, entity_type=entity_type, entity_id=entity_id)
    if row is not None and row.source_fingerprint == source_fingerprint:
        return row
    return None


def upsert_artifact(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    kind: str,
    entity_type: str,
    entity_id: str,
    title: str,
    content: dict,
    source_fingerprint: str,
    provider: str = "",
    is_mock: bool = True,
    prompt_version: str = "",
) -> AIArtifact:
    row = get_artifact(db, tenant_id=tenant_id, kind=kind, entity_type=entity_type, entity_id=entity_id)
    now = datetime.now(UTC)
    blob = json.dumps(content, default=str)
    if row is None:
        row = AIArtifact(
            tenant_id=tenant_id,
            created_by=actor_id,
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            content_json=blob,
            source_fingerprint=source_fingerprint,
            provider=provider,
            is_mock=is_mock,
            prompt_version=prompt_version,
            generated_at=now,
        )
        db.add(row)
        db.flush()
        return row
    row.title = title
    row.content_json = blob
    row.source_fingerprint = source_fingerprint
    row.provider = provider
    row.is_mock = is_mock
    row.prompt_version = prompt_version
    row.generated_at = now
    return row
