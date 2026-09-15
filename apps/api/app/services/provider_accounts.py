import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_credential, encrypt_credential
from app.models.integrations import ProviderAccount
from app.providers.calendar import (
    CalendarProvider,
    DisconnectedGoogleCalendarProvider,
    GoogleCalendarProvider,
)
from app.providers.email import DisconnectedGmailProvider, EmailProvider, GmailEmailProvider

GOOGLE_MAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def parse_scopes(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def has_scopes(account: ProviderAccount, required: list[str]) -> bool:
    granted = set(parse_scopes(account.scopes))
    return all(scope in granted for scope in required)


def connected_google_account(db: Session, tenant_id: UUID) -> ProviderAccount | None:
    return db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.tenant_id == tenant_id,
            ProviderAccount.provider == "google",
            ProviderAccount.status == "connected",
            ProviderAccount.deleted_at.is_(None),
        )
    )


def list_accounts(db: Session, tenant_id: UUID) -> list[ProviderAccount]:
    return list(
        db.scalars(
            select(ProviderAccount).where(
                ProviderAccount.tenant_id == tenant_id,
                ProviderAccount.deleted_at.is_(None),
            )
        ).all()
    )


def mark_success(account: ProviderAccount) -> None:
    account.last_success_at = datetime.now(UTC)
    account.last_error = ""


def mark_error(account: ProviderAccount, message: str) -> None:
    account.last_failure_at = datetime.now(UTC)
    account.last_error = message[:1000]


def persist_tokens(
    account: ProviderAccount,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_in: int,
    scopes: list[str] | None = None,
) -> None:
    account.access_token_encrypted = encrypt_credential(access_token)
    if refresh_token:
        account.refresh_token_encrypted = encrypt_credential(refresh_token)
    account.token_expires_at = datetime.now(UTC) + timedelta(seconds=max(expires_in - 60, 30))
    if scopes is not None:
        account.scopes = json.dumps(scopes)
    account.status = "connected"
    account.last_error = ""


def access_token(account: ProviderAccount) -> str:
    return decrypt_credential(account.access_token_encrypted)


def refresh_google_token(account: ProviderAccount, *, client_id: str, client_secret: str) -> bool:
    refresh = decrypt_credential(account.refresh_token_encrypted)
    if not refresh:
        mark_error(account, "Refresh token is missing.")
        return False
    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        },
        timeout=20.0,
    )
    if response.status_code >= 400:
        mark_error(account, f"Token refresh failed ({response.status_code}).")
        account.status = "error"
        return False
    payload = response.json()
    persist_tokens(
        account,
        access_token=str(payload.get("access_token") or ""),
        refresh_token=refresh,
        expires_in=int(payload.get("expires_in") or 3600),
        scopes=str(payload.get("scope") or "").split() or None,
    )
    mark_success(account)
    return True


def ensure_fresh_token(db: Session, account: ProviderAccount, *, client_id: str, client_secret: str) -> str:
    expires = account.token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires is None or expires <= datetime.now(UTC) + timedelta(minutes=2):
        refresh_google_token(account, client_id=client_id, client_secret=client_secret)
        db.flush()
    return access_token(account)


def gmail_provider_for_tenant(db: Session, tenant_id: UUID) -> EmailProvider:
    account = connected_google_account(db, tenant_id)
    if account is None or not has_scopes(account, ["https://www.googleapis.com/auth/gmail.send"]):
        return DisconnectedGmailProvider()
    settings = get_settings()
    token = ensure_fresh_token(
        db,
        account,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
    return GmailEmailProvider(
        access_token=token,
        last_success_at=account.last_success_at,
        last_failure_at=account.last_failure_at,
        last_error=account.last_error,
    )


def calendar_provider_for_tenant(db: Session, tenant_id: UUID) -> CalendarProvider:
    account = connected_google_account(db, tenant_id)
    if account is None or not has_scopes(account, ["https://www.googleapis.com/auth/calendar.events"]):
        return DisconnectedGoogleCalendarProvider()
    settings = get_settings()
    token = ensure_fresh_token(
        db,
        account,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
    return GoogleCalendarProvider(
        access_token=token,
        last_success_at=account.last_success_at,
        last_failure_at=account.last_failure_at,
        last_error=account.last_error,
    )


def upsert_token_account(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    provider: str,
    access_token: str,
    account_key: str = "default",
    extra: dict | None = None,
) -> ProviderAccount:
    row = db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.tenant_id == tenant_id,
            ProviderAccount.provider == provider,
            ProviderAccount.account_key == account_key,
            ProviderAccount.deleted_at.is_(None),
        )
    )
    if row is None:
        row = ProviderAccount(
            tenant_id=tenant_id,
            created_by=actor_id,
            provider=provider,
            account_key=account_key,
        )
        db.add(row)
    extra = extra or {}
    row.provider_account_id = str(
        extra.get("account_id")
        or extra.get("from_number")
        or extra.get("assistant_id")
        or extra.get("actor_id")
        or extra.get("sid")
        or row.provider_account_id
    )
    persist_tokens(row, access_token=access_token, refresh_token=None, expires_in=int(extra.get("expires_in") or 86400 * 365))
    row.config_encrypted = encrypt_credential(json.dumps({key: value for key, value in extra.items() if key != "access_token"}))
    mark_success(row)
    return row


def public_account(account: ProviderAccount) -> dict:
    scopes = parse_scopes(account.scopes)
    return {
        "id": account.id,
        "provider": account.provider,
        "provider_account_id": account.provider_account_id,
        "connected_user_id": account.connected_user_id,
        "account_key": account.account_key,
        "status": account.status,
        "scopes": scopes,
        "capabilities": {
            "gmail": has_scopes(account, ["https://www.googleapis.com/auth/gmail.send"]),
            "calendar": has_scopes(account, ["https://www.googleapis.com/auth/calendar.events"]),
        },
        "last_sync_at": account.last_sync_at,
        "last_success_at": account.last_success_at,
        "last_failure_at": account.last_failure_at,
        "last_error": account.last_error,
    }
