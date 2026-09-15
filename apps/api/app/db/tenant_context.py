"""Transaction-local Postgres tenant context. Never interpolate tenant IDs into SQL."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import tenant_id_ctx

SETTING_TENANT = "app.current_tenant_id"
SETTING_LOGIN_EMAIL = "app.login_email"
SETTING_REFRESH_HASH = "app.refresh_token_hash"
SETTING_WEBHOOK_HASH = "app.webhook_token_hash"


def supports_rls(db: Session) -> bool:
    bind = db.get_bind()
    return bind.dialect.name == "postgresql"


def _set_config(db: Session, key: str, value: str) -> None:
    if not supports_rls(db):
        return
    db.execute(text("SELECT set_config(:key, :value, true)"), {"key": key, "value": value})


def set_tenant_context(db: Session, tenant_id: UUID | None) -> None:
    value = str(tenant_id) if tenant_id else ""
    _set_config(db, SETTING_TENANT, value)
    tenant_id_ctx.set(value or "-")


def set_login_email(db: Session, email: str) -> None:
    _set_config(db, SETTING_LOGIN_EMAIL, email.lower().strip())


def set_refresh_token_hash(db: Session, token_hash: str) -> None:
    _set_config(db, SETTING_REFRESH_HASH, token_hash)


def set_webhook_token_hash(db: Session, token_hash: str) -> None:
    _set_config(db, SETTING_WEBHOOK_HASH, token_hash)


def clear_lookup_context(db: Session) -> None:
    _set_config(db, SETTING_LOGIN_EMAIL, "")
    _set_config(db, SETTING_REFRESH_HASH, "")
    _set_config(db, SETTING_WEBHOOK_HASH, "")


def clear_tenant_context(db: Session) -> None:
    set_tenant_context(db, None)
    clear_lookup_context(db)
