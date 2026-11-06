"""Transaction-local Postgres tenant context. Never interpolate tenant IDs into SQL."""

from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.core.logging import tenant_id_ctx

SETTING_TENANT = "app.current_tenant_id"
SETTING_LOGIN_EMAIL = "app.login_email"
SETTING_REFRESH_HASH = "app.refresh_token_hash"
SETTING_WEBHOOK_HASH = "app.webhook_token_hash"
SETTING_FORM_HASH = "app.form_token_hash"
SETTING_LEAD_INTAKE = "app.lead_intake"

INFO_TENANT = "rls_tenant_id"
INFO_LOGIN_EMAIL = "rls_login_email"
INFO_REFRESH_HASH = "rls_refresh_hash"
INFO_WEBHOOK_HASH = "rls_webhook_hash"
INFO_FORM_HASH = "rls_form_hash"
INFO_LEAD_INTAKE = "rls_lead_intake"


def supports_rls(db: Session) -> bool:
    bind = db.get_bind()
    return bind.dialect.name == "postgresql"


def _apply_config(connection: Connection, key: str, value: str) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(text("SELECT set_config(:key, :value, true)"), {"key": key, "value": value})


def _set_config(db: Session, key: str, value: str) -> None:
    if not supports_rls(db):
        return
    db.execute(text("SELECT set_config(:key, :value, true)"), {"key": key, "value": value})


def set_tenant_context(db: Session, tenant_id: UUID | None) -> None:
    value = str(tenant_id) if tenant_id else ""
    db.info[INFO_TENANT] = value
    _set_config(db, SETTING_TENANT, value)
    tenant_id_ctx.set(value or "-")


def set_login_email(db: Session, email: str) -> None:
    value = email.lower().strip()
    db.info[INFO_LOGIN_EMAIL] = value
    _set_config(db, SETTING_LOGIN_EMAIL, value)


def set_refresh_token_hash(db: Session, token_hash: str) -> None:
    db.info[INFO_REFRESH_HASH] = token_hash
    _set_config(db, SETTING_REFRESH_HASH, token_hash)


def set_webhook_token_hash(db: Session, token_hash: str) -> None:
    db.info[INFO_WEBHOOK_HASH] = token_hash
    _set_config(db, SETTING_WEBHOOK_HASH, token_hash)


def set_form_token_hash(db: Session, token_hash: str) -> None:
    db.info[INFO_FORM_HASH] = token_hash
    _set_config(db, SETTING_FORM_HASH, token_hash)


def set_lead_intake(db: Session, enabled: bool) -> None:
    """Let the lead webhook and its worker see unbound receipts and every form mapping.

    A normal request never sets this. It does not by itself authorize a write into
    another tenant: binding inserts still require that tenant's context.
    """
    value = "1" if enabled else ""
    db.info[INFO_LEAD_INTAKE] = value
    _set_config(db, SETTING_LEAD_INTAKE, value)


def clear_lookup_context(db: Session) -> None:
    db.info[INFO_LOGIN_EMAIL] = ""
    db.info[INFO_REFRESH_HASH] = ""
    db.info[INFO_WEBHOOK_HASH] = ""
    _set_config(db, SETTING_LOGIN_EMAIL, "")
    _set_config(db, SETTING_REFRESH_HASH, "")
    _set_config(db, SETTING_WEBHOOK_HASH, "")


def clear_tenant_context(db: Session) -> None:
    set_tenant_context(db, None)
    clear_lookup_context(db)


@event.listens_for(Session, "after_begin")
def _restore_rls_after_begin(session: Session, _transaction: object, connection: Connection) -> None:
    """SET LOCAL dies at COMMIT. Re-apply the same tenant on the next transaction."""
    if connection.dialect.name != "postgresql":
        return
    pairs = (
        (INFO_TENANT, SETTING_TENANT),
        (INFO_LOGIN_EMAIL, SETTING_LOGIN_EMAIL),
        (INFO_REFRESH_HASH, SETTING_REFRESH_HASH),
        (INFO_WEBHOOK_HASH, SETTING_WEBHOOK_HASH),
        (INFO_FORM_HASH, SETTING_FORM_HASH),
        (INFO_LEAD_INTAKE, SETTING_LEAD_INTAKE),
    )
    for info_key, setting_key in pairs:
        if info_key not in session.info:
            continue
        _apply_config(connection, setting_key, str(session.info.get(info_key) or ""))
