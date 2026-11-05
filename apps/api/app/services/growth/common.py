"""Shared helpers for the Social Growth services."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.identity import FeatureFlag, Tenant

FLAG_KEY = "ENABLE_SOCIAL_GROWTH"
PUBLISHABLE_PLATFORMS = ("facebook", "instagram")
FORMATS = ("image", "carousel", "reel", "text")
PLATFORM_FORMATS = {
    "instagram": ("image", "carousel", "reel"),
    "facebook": ("image", "carousel", "reel", "text"),
}


def now() -> datetime:
    return datetime.now(UTC)


def aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def loads(raw: str | None, default: Any) -> Any:
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def parse_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def growth_enabled(db: Session, tenant_id: UUID) -> bool:
    row = db.scalar(select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id, FeatureFlag.key == FLAG_KEY))
    return bool(row is not None and row.enabled)


def operating_mode(db: Session, tenant_id: UUID) -> str:
    tenant = db.get(Tenant, tenant_id)
    return ((tenant.operating_mode if tenant is not None else "") or "DEMO").strip().upper()


def publish_mode() -> str:
    return (get_settings().social_growth_publish_mode or "disabled").strip().lower()


def insights_mode() -> str:
    return (get_settings().social_growth_insights_mode or "disabled").strip().lower()


def iso(moment: datetime | None) -> str:
    stamped = aware(moment)
    return stamped.isoformat() if stamped is not None else ""
