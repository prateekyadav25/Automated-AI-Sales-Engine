"""Store growth media in object storage and serve it through the existing public media route."""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt_credential
from app.models.growth import GrowthAsset
from app.models.social import SocialImage
from app.providers.object_storage import get_object_storage
from app.providers.social import provider_can_fetch
from app.services.growth.common import dumps, loads
from app.services.public_forms import hash_form_token

_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "video/mp4": ".mp4"}
COMMERCIAL_PROVENANCE = {"rendered", "model_generated", "operator_upload"}


def public_ready(url: str) -> bool:
    """Meta fetches media itself. A loopback or plain-http address is not ready."""
    return bool(url) and url.startswith("https://") and provider_can_fetch(url)


def store_asset(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    data: bytes,
    mime: str,
    role: str,
    creative_id: UUID | None = None,
    position: int = 0,
    template: str = "",
    provenance: str = "rendered",
    model_id: str = "",
    width: int | None = None,
    height: int | None = None,
    duration_ms: int | None = None,
    quality_state: str = "pending",
    quality: dict | None = None,
) -> GrowthAsset:
    asset_id = uuid4()
    key = f"tenant/{tenant_id}/growth/{asset_id}/{role}{_EXTENSIONS.get(mime, '.bin')}"
    get_object_storage().put(key, data, content_type=mime)
    raw = secrets.token_urlsafe(32)
    image = SocialImage(
        tenant_id=tenant_id,
        created_by=actor_id,
        object_key=key,
        content_type=mime,
        token_hash=hash_form_token(raw),
        token_encrypted=encrypt_credential(raw),
    )
    db.add(image)
    db.flush()
    base = get_settings().public_api_base_url.rstrip("/") or "http://localhost:8000"
    row = GrowthAsset(
        id=asset_id,
        tenant_id=tenant_id,
        created_by=actor_id,
        creative_id=creative_id,
        role=role,
        position=position,
        mime=mime,
        width=width,
        height=height,
        duration_ms=duration_ms,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        object_key=key,
        social_image_id=image.id,
        public_url=f"{base}/api/v1/public/media/{raw}",
        template=template,
        provenance=provenance,
        model_id=model_id,
        quality_state=quality_state,
        quality_json=dumps(quality or {}),
    )
    db.add(row)
    db.flush()
    return row


def owned_asset(db: Session, tenant_id: UUID, asset_id: UUID) -> GrowthAsset:
    row = db.scalar(
        select(GrowthAsset).where(
            GrowthAsset.tenant_id == tenant_id,
            GrowthAsset.id == asset_id,
            GrowthAsset.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return row


def read_asset(db: Session, tenant_id: UUID, asset_id: UUID) -> tuple[bytes, str]:
    row = owned_asset(db, tenant_id, asset_id)
    try:
        return get_object_storage().get(row.object_key), row.mime
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Asset bytes are missing from storage") from exc


def asset_bytes(row: GrowthAsset) -> bytes:
    return get_object_storage().get(row.object_key)


def creative_assets(db: Session, tenant_id: UUID, creative_id: UUID) -> list[GrowthAsset]:
    return list(
        db.scalars(
            select(GrowthAsset)
            .where(
                GrowthAsset.tenant_id == tenant_id,
                GrowthAsset.creative_id == creative_id,
                GrowthAsset.deleted_at.is_(None),
            )
            .order_by(GrowthAsset.role.asc(), GrowthAsset.position.asc())
        ).all()
    )


def asset_out(row: GrowthAsset) -> dict:
    return {
        "id": str(row.id),
        "role": row.role,
        "position": row.position,
        "mime": row.mime,
        "width": row.width,
        "height": row.height,
        "duration_ms": row.duration_ms,
        "size_bytes": row.size_bytes,
        "template": row.template,
        "provenance": row.provenance,
        "model_id": row.model_id,
        "quality_state": row.quality_state,
        "quality": loads(row.quality_json, {}),
        "preview_url": row.public_url,
        "public_media_ready": public_ready(row.public_url),
        "commercial": row.provenance in COMMERCIAL_PROVENANCE and row.quality_state == "passed",
    }
