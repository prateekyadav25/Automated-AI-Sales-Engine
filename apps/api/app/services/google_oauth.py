import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_credential, encrypt_credential
from app.models.integrations import ProviderAccount
from app.services.audit import write_audit
from app.services.provider_accounts import (
    GOOGLE_CALENDAR_SCOPES,
    GOOGLE_MAIL_SCOPES,
    persist_tokens,
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def requested_scopes(capabilities: str) -> list[str]:
    selected = {item.strip().lower() for item in (capabilities or "mail,calendar").split(",") if item.strip()}
    scopes = list(GOOGLE_MAIL_SCOPES)
    if "calendar" in selected or not selected:
        scopes.extend(GOOGLE_CALENDAR_SCOPES)
    return list(dict.fromkeys(scopes))


def sign_state(*, tenant_id: UUID, user_id: UUID, scopes: list[str]) -> str:
    settings = get_settings()
    payload = {
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
        "nonce": secrets.token_urlsafe(16),
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "typ": "google_oauth",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def read_state(state: str) -> dict:
    settings = get_settings()
    payload = jwt.decode(state, settings.secret_key, algorithms=["HS256"])
    if payload.get("typ") != "google_oauth":
        raise jwt.InvalidTokenError("Invalid OAuth state")
    return payload


def authorization_url(*, tenant_id: UUID, user_id: UUID, capabilities: str = "mail,calendar") -> str:
    settings = get_settings()
    scopes = requested_scopes(capabilities)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": sign_state(tenant_id=tenant_id, user_id=user_id, scopes=scopes),
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def google_configured() -> bool:
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


def exchange_code(code: str) -> dict:
    settings = get_settings()
    response = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json()


def fetch_email(access_token: str) -> str:
    response = httpx.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=20.0)
    if response.status_code >= 400:
        return ""
    return str(response.json().get("email") or "")


def upsert_google_account(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    token_payload: dict,
    requested: list[str],
) -> ProviderAccount:
    access_token = str(token_payload.get("access_token") or "")
    refresh_token = str(token_payload.get("refresh_token") or "")
    granted = str(token_payload.get("scope") or "").split() or requested
    email = fetch_email(access_token)
    row = db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.tenant_id == tenant_id,
            ProviderAccount.provider == "google",
            ProviderAccount.connected_user_id == user_id,
            ProviderAccount.deleted_at.is_(None),
        )
    )
    if row is None:
        row = ProviderAccount(
            tenant_id=tenant_id,
            created_by=user_id,
            provider="google",
            account_key=str(user_id),
            connected_user_id=user_id,
            status="connected",
        )
        db.add(row)
    row.provider_account_id = email
    persist_tokens(
        row,
        access_token=access_token,
        refresh_token=refresh_token or None,
        expires_in=int(token_payload.get("expires_in") or 3600),
        scopes=granted,
    )
    if not refresh_token and not row.refresh_token_encrypted:
        row.refresh_token_encrypted = encrypt_credential("")
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="integration.google.connect",
        entity_type="provider_account",
        entity_id=str(row.id),
        after={"provider_account_id": email, "scopes": granted},
    )
    db.flush()
    return row


def disconnect_google(db: Session, *, tenant_id: UUID, actor_id: UUID, account: ProviderAccount) -> None:
    refresh = ""
    try:
        refresh = decrypt_credential(account.refresh_token_encrypted)
    except ValueError:
        refresh = ""
    if refresh:
        try:
            httpx.post(GOOGLE_REVOKE_URL, params={"token": refresh}, timeout=10.0)
        except httpx.HTTPError:
            pass
    account.status = "disconnected"
    account.access_token_encrypted = ""
    account.refresh_token_encrypted = ""
    account.last_error = ""
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="integration.google.disconnect",
        entity_type="provider_account",
        entity_id=str(account.id),
        after={"status": "disconnected"},
    )
