from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.funnel import PublicFormKey
from app.services.audit import write_audit


def hash_form_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_form_key(db: Session, *, tenant_id: UUID, actor_id: UUID, name: str = "website") -> tuple[PublicFormKey, str]:
    raw = secrets.token_urlsafe(32)
    row = PublicFormKey(
        tenant_id=tenant_id,
        created_by=actor_id,
        name=name.strip() or "website",
        token_hash=hash_form_token(raw),
        status="active",
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="public_form.create",
        entity_type="public_form_key",
        entity_id=str(row.id),
        after={"name": row.name},
    )
    return row, raw


def resolve_form_key(db: Session, raw_token: str) -> PublicFormKey:
    hashed = hash_form_token(raw_token)
    row = db.scalar(
        select(PublicFormKey).where(
            PublicFormKey.token_hash == hashed,
            PublicFormKey.status == "active",
            PublicFormKey.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown public form key")
    row.last_used_at = datetime.now(UTC)
    return row


def list_form_keys(db: Session, tenant_id: UUID) -> list[PublicFormKey]:
    return list(
        db.scalars(
            select(PublicFormKey).where(PublicFormKey.tenant_id == tenant_id, PublicFormKey.deleted_at.is_(None)).order_by(PublicFormKey.created_at.desc())
        )
    )


def revoke_form_key(db: Session, row: PublicFormKey) -> PublicFormKey:
    row.status = "revoked"
    return row
