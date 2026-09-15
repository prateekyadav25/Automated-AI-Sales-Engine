import hashlib
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tenant_context import set_webhook_token_hash
from app.models.integrations import WebhookRoute

DEMO_WEBHOOK_PREFIX = "agrayian-demo-webhook"


def hash_routing_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def demo_routing_token(slug: str, provider: str) -> str:
    return hashlib.sha256(f"{DEMO_WEBHOOK_PREFIX}:{slug}:{provider}".encode("utf-8")).hexdigest()


def ensure_route(db: Session, *, tenant_id: UUID, provider: str, raw_token: str | None = None, rotate: bool = False) -> str:
    provider = provider.strip().lower()
    row = db.scalar(
        select(WebhookRoute).where(
            WebhookRoute.tenant_id == tenant_id,
            WebhookRoute.provider == provider,
            WebhookRoute.deleted_at.is_(None),
        )
    )
    if row is None:
        raw = raw_token or secrets.token_urlsafe(32)
        db.add(WebhookRoute(tenant_id=tenant_id, provider=provider, token_hash=hash_routing_token(raw)))
        db.flush()
        return raw
    if raw_token and row.token_hash == hash_routing_token(raw_token):
        return raw_token
    if rotate:
        raw = raw_token or secrets.token_urlsafe(32)
        row.token_hash = hash_routing_token(raw)
        return raw
    return ""


def resolve_tenant_id(db: Session, *, provider: str, raw_token: str) -> UUID | None:
    hashed = hash_routing_token(raw_token)
    set_webhook_token_hash(db, hashed)
    row = db.scalar(
        select(WebhookRoute).where(
            WebhookRoute.provider == provider.strip().lower(),
            WebhookRoute.token_hash == hashed,
            WebhookRoute.deleted_at.is_(None),
        )
    )
    return row.tenant_id if row is not None else None
