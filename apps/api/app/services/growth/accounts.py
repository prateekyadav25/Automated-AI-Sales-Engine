"""Independently managed Facebook Pages and Instagram professional accounts.

Each account keeps its own encrypted credential. A token is never returned.
Expiry and scopes come from Meta's debug_token response, not from a default.
A refused or expired token moves the account to needs_reconnect.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_credential, encrypt_credential
from app.models.growth import GrowthAccount, GrowthCalendarItem
from app.models.integrations import ProviderAccount
from app.providers.meta_growth import MetaGrowthClient, graph_version
from app.services.audit import write_audit
from app.services.demo_guard import organic_metrics_block
from app.services.growth.acceptance import require_authorized
from app.services.growth.common import (
    PUBLISHABLE_PLATFORMS,
    aware,
    dumps,
    insights_mode,
    iso,
    loads,
    now,
    operating_mode,
)

PROVIDER = "meta-growth"
REQUIRED_SCOPES = {
    "facebook": {
        "publish": ("pages_manage_posts", "pages_read_engagement", "pages_show_list"),
        "insights": ("read_insights", "pages_read_engagement"),
    },
    "instagram": {
        "publish": ("instagram_basic", "instagram_content_publish", "pages_read_engagement", "pages_show_list"),
        "insights": ("instagram_basic", "instagram_manage_insights", "pages_read_engagement"),
        "benchmarks": ("instagram_basic", "instagram_manage_insights"),
    },
}
DEFAULT_WINDOWS = [{"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "18:00"}]
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _credential(db: Session, tenant_id: UUID, platform: str, external_id: str) -> ProviderAccount | None:
    return db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.tenant_id == tenant_id,
            ProviderAccount.provider == PROVIDER,
            ProviderAccount.account_key == f"{platform}:{external_id}",
            ProviderAccount.deleted_at.is_(None),
        )
    )


def owned_account(db: Session, tenant_id: UUID, account_id: UUID) -> GrowthAccount:
    row = db.scalar(
        select(GrowthAccount).where(
            GrowthAccount.tenant_id == tenant_id,
            GrowthAccount.id == account_id,
            GrowthAccount.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return row


def account_token(db: Session, account: GrowthAccount) -> str:
    if account.provider_account_id is None:
        return ""
    credential = db.get(ProviderAccount, account.provider_account_id)
    if credential is None or credential.tenant_id != account.tenant_id or credential.deleted_at is not None:
        return ""
    try:
        return decrypt_credential(credential.access_token_encrypted)
    except ValueError:
        return ""


def token_problem(account: GrowthAccount) -> str:
    """The reason this account cannot act now, or an empty string."""
    if account.status in {"disconnected", "revoked"}:
        return "The account is disconnected. Reconnect it before publishing or reading insights."
    if account.status == "needs_reconnect":
        reason = (account.last_error or "Meta refused the stored token.").strip()
        return reason if "reconnect" in reason.casefold() else f"{reason.rstrip('.')}. Reconnect the account."
    moment = now()
    expires = aware(account.token_expires_at)
    if expires is not None and expires <= moment:
        return "The access token expired. Reconnect the account."
    data_access = aware(account.data_access_expires_at)
    if data_access is not None and data_access <= moment:
        return "Meta data access for this token expired. The person who connected it must log in again."
    return ""


def capabilities(account: GrowthAccount) -> dict:
    return loads(account.capabilities, {})


def live_read_block(db: Session, tenant_id: UUID) -> str:
    """Reads from Meta need the live insights mode and, on a DEMO tenant, an authorized scope."""
    if insights_mode() != "live":
        return "Live Meta reads are disabled in this deployment (SOCIAL_GROWTH_INSIGHTS_MODE). Nothing was requested."
    return organic_metrics_block(db, tenant_id)


def live_client(db: Session, account: GrowthAccount) -> MetaGrowthClient | None:
    token = account_token(db, account)
    if not token:
        return None
    return MetaGrowthClient(client=httpx.Client(timeout=60.0), access_token=token, app_secret=get_settings().meta_app_secret)


def connect_account(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    platform: str,
    external_id: str,
    access_token: str,
    page_id: str = "",
    name: str = "",
    username: str = "",
    timezone: str = "UTC",
) -> GrowthAccount:
    platform = platform.strip().lower()
    external_id = external_id.strip()
    if platform not in PUBLISHABLE_PLATFORMS:
        raise HTTPException(status_code=422, detail="Choose facebook or instagram.")
    if not re.fullmatch(r"[0-9]{3,40}", external_id):
        raise HTTPException(status_code=422, detail="The Page or Instagram account id must be the numeric id Meta returned.")
    if not access_token.strip():
        raise HTTPException(status_code=422, detail="An access token is required. It is stored encrypted and never shown again.")
    if platform == "instagram" and not re.fullmatch(r"[0-9]{3,40}", page_id.strip()):
        raise HTTPException(status_code=422, detail="An Instagram professional account is published through its linked Facebook Page. Supply that Page id.")
    credential = _credential(db, tenant_id, platform, external_id)
    if credential is None:
        credential = ProviderAccount(
            tenant_id=tenant_id,
            created_by=actor_id,
            provider=PROVIDER,
            account_key=f"{platform}:{external_id}",
            connected_user_id=actor_id,
        )
        db.add(credential)
    credential.provider_account_id = external_id
    credential.access_token_encrypted = encrypt_credential(access_token.strip())
    credential.token_expires_at = None
    credential.status = "connected"
    credential.last_error = ""
    credential.config_encrypted = encrypt_credential(dumps({"platform": platform, "page_id": page_id.strip()}))
    db.flush()
    account = db.scalar(
        select(GrowthAccount).where(
            GrowthAccount.tenant_id == tenant_id,
            GrowthAccount.platform == platform,
            GrowthAccount.external_id == external_id,
        )
    )
    reconnect = account is not None
    if account is None:
        account = GrowthAccount(
            tenant_id=tenant_id,
            created_by=actor_id,
            platform=platform,
            external_id=external_id,
            posting_windows=dumps(DEFAULT_WINDOWS),
        )
        db.add(account)
    account.deleted_at = None
    account.page_id = page_id.strip() if platform == "instagram" else external_id
    account.name = name.strip()[:200] or account.name
    account.username = username.strip().lstrip("@")[:120] or account.username
    account.timezone = timezone.strip() or account.timezone or "UTC"
    account.provider_account_id = credential.id
    account.provenance = "live"
    account.status = "unverified"
    account.last_error = ""
    account.token_expires_at = None
    account.data_access_expires_at = None
    account.api_version = graph_version()
    db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="growth.account_reconnect" if reconnect else "growth.account_connect",
        entity_type="growth_account",
        entity_id=str(account.id),
        after={"platform": platform, "external_id": external_id, "page_id": account.page_id, "status": account.status},
    )
    return account


def create_fixture_account(db: Session, *, tenant_id: UUID, actor_id: UUID, platform: str, name: str) -> GrowthAccount:
    if operating_mode(db, tenant_id) == "PRODUCTION":
        raise HTTPException(status_code=409, detail="A PRODUCTION workspace cannot add a fixture account.")
    platform = platform.strip().lower()
    if platform not in PUBLISHABLE_PLATFORMS:
        raise HTTPException(status_code=422, detail="Choose facebook or instagram.")
    account = GrowthAccount(
        tenant_id=tenant_id,
        created_by=actor_id,
        platform=platform,
        external_id=f"fixture{uuid4().int % 10**12:012d}",
        page_id="",
        name=(name.strip() or f"Test {platform} account")[:200],
        provenance="fixture",
        status="fixture",
        posting_windows=dumps(DEFAULT_WINDOWS),
        capabilities=dumps({"publish": False, "insights": False, "reason": "Fixture account. It never reaches Meta."}),
        api_version=graph_version(),
    )
    db.add(account)
    db.flush()
    if platform == "instagram":
        account.page_id = account.external_id
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.account_fixture", entity_type="growth_account", entity_id=str(account.id), after={"platform": platform})
    return account


def _timestamp(value) -> datetime | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return datetime.fromtimestamp(number, tz=UTC)


def verify_account(db: Session, *, tenant_id: UUID, actor_id: UUID | None, account_id: UUID, client: MetaGrowthClient | None = None) -> dict:
    account = owned_account(db, tenant_id, account_id)
    if account.provenance == "fixture":
        return {"status": account.status, "detail": "Fixture accounts are not verified against Meta.", "account": account_out(account)}
    owned = False
    if client is None:
        blocked = live_read_block(db, tenant_id)
        if blocked:
            return {"status": account.status, "detail": blocked, "account": account_out(account)}
        denied = require_authorized(db, tenant_id, "token_verification")
        if denied:
            return {"status": account.status, "detail": denied, "account": account_out(account)}
        client = live_client(db, account)
        owned = True
        if client is None:
            account.status = "needs_reconnect"
            account.last_error = "No stored token. Reconnect the account."
            return {"status": account.status, "detail": account.last_error, "account": account_out(account)}
    settings = get_settings()
    try:
        granted: list[str] = []
        token_checked = False
        if settings.meta_app_id and settings.meta_app_secret:
            debug = client.debug_token(app_id=settings.meta_app_id, app_secret=settings.meta_app_secret, input_token=account_token(db, account))
            payload = debug.data.get("data") if debug.ok and isinstance(debug.data.get("data"), dict) else {}
            if debug.ok and payload:
                token_checked = True
                if not payload.get("is_valid", False):
                    account.status = "needs_reconnect"
                    account.last_error = "Meta reports the stored token is not valid."
                    account.last_verified_at = now()
                    return {"status": account.status, "detail": account.last_error, "account": account_out(account)}
                account.token_expires_at = _timestamp(payload.get("expires_at"))
                account.data_access_expires_at = _timestamp(payload.get("data_access_expires_at"))
                granted = [str(item) for item in payload.get("scopes") or []]
        identity = client.instagram_account(account.external_id) if account.platform == "instagram" else client.page(account.external_id)
        account.last_verified_at = now()
        if not identity.ok:
            if identity.failure_class == "AUTH":
                account.status = "needs_reconnect"
            elif identity.failure_class == "PERMISSION":
                account.status = "missing_permissions"
            account.last_error = identity.error_message
            return {"status": account.status, "detail": identity.error_message, "account": account_out(account)}
        data = identity.data
        account.name = str(data.get("name") or account.name)[:200]
        account.username = str(data.get("username") or account.username)[:120]
        followers = data.get("followers_count")
        if isinstance(followers, int) and not isinstance(followers, bool) and followers >= 0:
            account.followers_count = followers
            account.followers_observed_at = now()
        needs = REQUIRED_SCOPES.get(account.platform, {})
        missing = sorted({scope for scopes in needs.values() for scope in scopes if scope not in granted}) if token_checked else []
        account.granted_scopes = dumps(granted)
        account.missing_scopes = dumps(missing)
        caps = {name: (all(scope in granted for scope in scopes) if token_checked else None) for name, scopes in needs.items()}
        caps["checked"] = token_checked
        if not token_checked:
            caps["reason"] = "Set META_APP_ID and META_APP_SECRET so scopes and expiry can be read from debug_token."
        account.capabilities = dumps(caps)
        expired = token_problem(account)
        if expired:
            account.status = "expired"
            account.last_error = expired
        elif token_checked and not caps.get("publish"):
            account.status = "missing_permissions"
            account.last_error = "Publishing permission is missing: " + ", ".join(scope for scope in needs.get("publish", ()) if scope not in granted)
        else:
            account.status = "connected" if token_checked else "unverified"
            account.last_error = ""
        account.api_version = client.version
        db.flush()
        write_audit(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="growth.account_verify",
            entity_type="growth_account",
            entity_id=str(account.id),
            after={"status": account.status, "missing_scopes": missing, "token_checked": token_checked},
            actor_type="human" if actor_id else "ai",
        )
        return {"status": account.status, "detail": account.last_error or "Account verified.", "account": account_out(account)}
    finally:
        if owned and client is not None:
            current = loads(account.capabilities, {})
            current["evidence"] = "provider" if account.status == "connected" else "provider_failed"
            account.capabilities = dumps(current)
            db.flush()
            client.close()


def mark_auth_failure(account: GrowthAccount, message: str) -> None:
    account.status = "needs_reconnect"
    account.last_error = (message or "Meta refused the stored token.")[:1000]


def _windows(raw: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for window in raw:
        days = sorted({int(day) for day in window.get("days") or [] if str(day).isdigit() and 0 <= int(day) <= 6})
        start = str(window.get("start") or "").strip()
        end = str(window.get("end") or "").strip()
        if not days or not _TIME.match(start) or not _TIME.match(end) or end <= start:
            raise HTTPException(status_code=422, detail="Each posting window needs weekdays 0-6 and a start before its end in HH:MM.")
        cleaned.append({"days": days, "start": start, "end": end})
    if not cleaned:
        raise HTTPException(status_code=422, detail="At least one posting window is required.")
    return cleaned


def update_account(db: Session, *, tenant_id: UUID, actor_id: UUID, account_id: UUID, posting_windows: list[dict] | None, daily_cap: int | None, timezone: str | None) -> GrowthAccount:
    account = owned_account(db, tenant_id, account_id)
    before = account_out(account)
    if posting_windows is not None:
        account.posting_windows = dumps(_windows(posting_windows))
    if daily_cap is not None:
        if not 0 <= daily_cap <= 25:
            raise HTTPException(status_code=422, detail="The daily cap must be between 0 and 25 posts.")
        account.daily_cap = daily_cap
    if timezone is not None:
        try:
            ZoneInfo(timezone.strip())
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Unknown time zone.") from exc
        account.timezone = timezone.strip()
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.account_update", entity_type="growth_account", entity_id=str(account.id), before=before, after=account_out(account))
    return account


def disconnect_account(db: Session, *, tenant_id: UUID, actor_id: UUID, account_id: UUID) -> GrowthAccount:
    account = owned_account(db, tenant_id, account_id)
    account.status = "disconnected"
    if account.provider_account_id is not None:
        credential = db.get(ProviderAccount, account.provider_account_id)
        if credential is not None and credential.tenant_id == tenant_id:
            credential.access_token_encrypted = ""
            credential.status = "revoked"
    pending = db.scalars(
        select(GrowthCalendarItem).where(
            GrowthCalendarItem.tenant_id == tenant_id,
            GrowthCalendarItem.account_id == account.id,
            GrowthCalendarItem.deleted_at.is_(None),
            GrowthCalendarItem.status.in_(["planned", "creative_ready", "needs_review", "approved", "scheduled"]),
        )
    ).all()
    for item in pending:
        item.status = "blocked"
        item.blocker = "The account was disconnected. Nothing will publish until it is reconnected."
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.account_disconnect", entity_type="growth_account", entity_id=str(account.id), after={"held_items": len(pending)})
    return account


def account_out(row: GrowthAccount) -> dict:
    problem = token_problem(row)
    capabilities = loads(row.capabilities, {})
    live_and_connected = row.provenance != "fixture" and row.status == "connected" and not problem
    posting_limit = f"This account allows {row.daily_cap} posts a day."
    if row.platform == "instagram":
        posting_limit += (
            f" Instagram's deployment pre-check is {get_settings().social_growth_instagram_daily_limit} publications in 24 hours."
            " The live quota is read only after publishing is authorized."
        )
    return {
        "id": str(row.id),
        "platform": row.platform,
        "external_id": row.external_id,
        "page_id": row.page_id,
        "name": row.name,
        "username": row.username,
        "provenance": row.provenance,
        "status": row.status,
        "token_expires_at": iso(row.token_expires_at),
        "data_access_expires_at": iso(row.data_access_expires_at),
        "granted_scopes": loads(row.granted_scopes, []),
        "missing_scopes": loads(row.missing_scopes, []),
        "capabilities": loads(row.capabilities, {}),
        "last_verified_at": iso(row.last_verified_at),
        "last_error": row.last_error,
        "timezone": row.timezone,
        "posting_windows": loads(row.posting_windows, []),
        "daily_cap": row.daily_cap,
        "api_version": row.api_version,
        "followers_count": row.followers_count,
        "followers_observed_at": iso(row.followers_observed_at),
        "problem": problem,
        "publish_eligible": live_and_connected and capabilities.get("publish") is True,
        "insights_eligible": live_and_connected and capabilities.get("insights") is True,
        "reconnect_required": bool(problem) or row.status in {"needs_reconnect", "expired", "revoked", "disconnected"},
        "posting_limit": posting_limit,
    }


def list_accounts(db: Session, tenant_id: UUID, *, include_disconnected: bool = True) -> list[GrowthAccount]:
    stmt = select(GrowthAccount).where(GrowthAccount.tenant_id == tenant_id, GrowthAccount.deleted_at.is_(None))
    if not include_disconnected:
        stmt = stmt.where(GrowthAccount.status.notin_(["disconnected", "revoked"]))
    return list(db.scalars(stmt.order_by(GrowthAccount.platform.asc(), GrowthAccount.name.asc())).all())
