from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_credential
from app.models.integrations import ProviderAccount
from app.services.autopilot_settings import get_or_create_settings


@dataclass
class ResolvedProvider:
    mode: str
    provider: str
    account_id: UUID | None
    reason: str
    uses_deployment_default: bool
    secrets: dict[str, str] = field(default_factory=dict)


def _account(db: Session, tenant_id: UUID, provider: str) -> ProviderAccount | None:
    return db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.tenant_id == tenant_id,
            ProviderAccount.provider == provider,
            ProviderAccount.status == "connected",
            ProviderAccount.deleted_at.is_(None),
        )
    )


def load_account_secrets(account: ProviderAccount) -> dict[str, str]:
    token = decrypt_credential(account.access_token_encrypted)
    extra: dict[str, str] = {}
    raw = ""
    encrypted = getattr(account, "config_encrypted", "") or ""
    if encrypted:
        raw = decrypt_credential(encrypted)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                extra = {str(key): str(value) for key, value in parsed.items() if value is not None}
        except json.JSONDecodeError:
            extra = {}
    extra.setdefault("account_id", account.provider_account_id)
    extra["access_token"] = token
    return extra


def resolve_provider(
    db: Session,
    *,
    tenant_id: UUID,
    provider: str,
    live_mode: str,
    deployment_configured: bool,
    deployment_secrets: dict[str, str] | None = None,
) -> ResolvedProvider:
    settings = get_or_create_settings(db, tenant_id=tenant_id)
    account = _account(db, tenant_id, provider)
    if account is not None:
        return ResolvedProvider(
            "LIVE",
            provider,
            account.id,
            "tenant credential",
            False,
            load_account_secrets(account),
        )
    if live_mode == "mock":
        return ResolvedProvider("MOCK", provider, None, "explicit mock mode", False)
    if deployment_configured and settings.allow_deployment_provider_defaults:
        return ResolvedProvider(
            "LIVE",
            provider,
            None,
            "deployment default",
            True,
            dict(deployment_secrets or {}),
        )
    if live_mode in {"live", "gmail", "google", "twilio", "vapi", "apify", "exotel", "openai", "recall"} and not deployment_configured:
        return ResolvedProvider("NOT_CONFIGURED", provider, None, "live mode without credentials", False)
    return ResolvedProvider("NOT_CONFIGURED", provider, None, "no tenant credential", False)


def resolve_channel(db: Session, tenant_id: UUID, channel: str) -> ResolvedProvider:
    cfg = get_settings()
    if channel == "email":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="google",
            live_mode=cfg.email_provider,
            deployment_configured=bool(cfg.google_client_id),
        )
    if channel == "calendar":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="google",
            live_mode=cfg.calendar_provider,
            deployment_configured=bool(cfg.google_client_id),
        )
    if channel == "linkedin":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="linkedin",
            live_mode=cfg.linkedin_ads_mode,
            deployment_configured=cfg.linkedin_ads_configured,
            deployment_secrets={
                "access_token": cfg.linkedin_access_token,
                "account_id": cfg.linkedin_ad_account_id,
            },
        )
    if channel == "meta":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="meta",
            live_mode=cfg.meta_ads_mode,
            deployment_configured=cfg.meta_ads_configured,
            deployment_secrets={
                "access_token": cfg.meta_access_token,
                "account_id": cfg.meta_ad_account_id,
            },
        )
    if channel == "twilio":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="twilio",
            live_mode=cfg.voice_provider,
            deployment_configured=cfg.twilio_configured,
            deployment_secrets={
                "access_token": cfg.twilio_auth_token,
                "account_sid": cfg.twilio_account_sid,
                "from_number": cfg.twilio_from_number,
                "twiml_url": cfg.twilio_twiml_url,
            },
        )
    if channel == "vapi":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="vapi",
            live_mode=cfg.voice_provider if cfg.voice_provider == "vapi" else cfg.voice_conversation_provider,
            deployment_configured=cfg.vapi_configured,
            deployment_secrets={
                "access_token": cfg.vapi_api_key,
                "assistant_id": cfg.vapi_assistant_id,
                "phone_number_id": cfg.vapi_phone_number_id,
            },
        )
    if channel == "exotel":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="exotel",
            live_mode="live" if cfg.exotel_configured else cfg.voice_provider,
            deployment_configured=cfg.exotel_configured,
            deployment_secrets={
                "access_token": cfg.exotel_api_token,
                "sid": cfg.exotel_sid,
                "api_key": cfg.exotel_api_key,
                "caller_id": cfg.exotel_caller_id,
                "subdomain": cfg.exotel_subdomain,
            },
        )
    if channel == "discovery":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="apify",
            live_mode=cfg.discovery_provider,
            deployment_configured=cfg.apify_configured,
            deployment_secrets={
                "access_token": cfg.resolved_apify_token,
                "actor_id": cfg.apify_actor_id,
                "process_token": cfg.apify_linkedin_process_token,
            },
        )
    if channel == "openai":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="openai",
            live_mode=cfg.llm_provider,
            deployment_configured=cfg.openai_configured,
            deployment_secrets={"access_token": cfg.openai_api_key},
        )
    if channel == "recall":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="recall",
            live_mode=cfg.meeting_capture_provider,
            deployment_configured=cfg.recall_configured,
            deployment_secrets={"access_token": cfg.recall_api_key},
        )
    if channel == "enrichment":
        return resolve_provider(
            db,
            tenant_id=tenant_id,
            provider="enrichment",
            live_mode=cfg.enrichment_provider,
            deployment_configured=cfg.enrichment_configured,
            deployment_secrets={"access_token": cfg.enrichment_api_key},
        )
    if channel == "whatsapp":
        account = _account(db, tenant_id, "whatsapp")
        if account:
            return ResolvedProvider("LIVE", "whatsapp", account.id, "tenant credential", False, load_account_secrets(account))
        return ResolvedProvider("NOT_CONFIGURED", "whatsapp", None, "WhatsApp provider is not configured", False)
    return ResolvedProvider("NOT_CONFIGURED", channel, None, "unknown channel", False)
