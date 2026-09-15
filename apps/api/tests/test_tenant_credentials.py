from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai.providers import NotConfiguredLLMProvider, OpenAILLMProvider, get_llm_provider
from app.core.config import get_settings
from app.db.session import get_session
from app.models.identity import User
from app.models.integrations import ProviderAccount, WebhookRoute
from app.providers.ads import LinkedInAdsProvider, MockAdsProvider, NotConfiguredAdsProvider, get_ads_provider
from app.providers.lead_discovery import (
    ApifyLeadDiscoveryProvider,
    MockLeadDiscoveryProvider,
    NotConfiguredDiscoveryProvider,
    get_lead_discovery_provider,
)
from app.providers.voice_telephony import TwilioTelephonyProvider
from app.services.pilot_readiness import activate_mode
from app.services.provider_accounts import upsert_token_account
from app.services.provider_provision import channel_modes
from app.services.provider_resolve import resolve_channel
from app.services.voice_router import compose_voice_provider
from app.services.webhook_routes import demo_routing_token, ensure_route, hash_routing_token
from tests.conftest import login


def _tenant(db):
    user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
    assert user is not None
    return user


def test_tenant_row_makes_ads_and_discovery_live_when_env_is_mock(client: TestClient, monkeypatch) -> None:
    login(client)
    monkeypatch.setenv("LINKEDIN_ADS_MODE", "mock")
    monkeypatch.setenv("DISCOVERY_PROVIDER", "mock")
    get_settings.cache_clear()
    db = get_session()
    try:
        user = _tenant(db)
        upsert_token_account(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            provider="linkedin",
            access_token="tenant-linkedin-token",
            extra={"account_id": "acct-1"},
        )
        upsert_token_account(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            provider="apify",
            access_token="tenant-apify-token",
            extra={"actor_id": "harvestapi/linkedin-profile-search"},
        )
        db.commit()
        ads = get_ads_provider("linkedin", db, user.tenant_id)
        discovery = get_lead_discovery_provider(db, user.tenant_id)
        linkedin = resolve_channel(db, user.tenant_id, "linkedin")
        found = resolve_channel(db, user.tenant_id, "discovery")
        assert isinstance(ads, LinkedInAdsProvider)
        assert ads.health().is_mock is False
        assert ads.health().connected is True
        assert linkedin.mode == "LIVE"
        assert linkedin.reason == "tenant credential"
        assert isinstance(discovery, ApifyLeadDiscoveryProvider)
        assert discovery.health()["is_mock"] is False
        assert discovery.health()["connected"] is True
        assert found.mode == "LIVE"
        health = client.get("/api/v1/integrations/providers", headers=login(client)).json()["data"]
        ads_row = next(row for row in health if row["name"] == "LinkedIn Ads")
        assert ads_row["mode"] == "LIVE"
        for row in db.scalars(select(ProviderAccount).where(ProviderAccount.tenant_id == user.tenant_id, ProviderAccount.provider.in_(["linkedin", "apify"]))).all():
            row.status = "disconnected"
        db.commit()
    finally:
        db.close()
        monkeypatch.delenv("LINKEDIN_ADS_MODE", raising=False)
        monkeypatch.delenv("DISCOVERY_PROVIDER", raising=False)
        get_settings.cache_clear()


def test_live_without_creds_is_not_silent_mock(monkeypatch) -> None:
    monkeypatch.setenv("LINKEDIN_ADS_MODE", "live")
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "")
    monkeypatch.setenv("LINKEDIN_AD_ACCOUNT_ID", "")
    monkeypatch.setenv("DISCOVERY_PROVIDER", "apify")
    monkeypatch.setenv("APIFY_API_TOKEN", "")
    monkeypatch.setenv("APIFY_ACTOR_ID", "")
    get_settings.cache_clear()
    try:
        ads = get_ads_provider("linkedin")
        discovery = get_lead_discovery_provider()
        assert isinstance(ads, NotConfiguredAdsProvider)
        assert not isinstance(ads, MockAdsProvider) or ads.health().is_mock is False
        assert ads.health().is_mock is False
        assert isinstance(discovery, NotConfiguredDiscoveryProvider)
        assert not isinstance(discovery, MockLeadDiscoveryProvider)
        assert discovery.health()["is_mock"] is False
    finally:
        monkeypatch.delenv("LINKEDIN_ADS_MODE", raising=False)
        monkeypatch.delenv("DISCOVERY_PROVIDER", raising=False)
        get_settings.cache_clear()


def test_tenant_row_makes_voice_live_when_env_is_mock(client: TestClient, monkeypatch) -> None:
    login(client)
    monkeypatch.setenv("VOICE_PROVIDER", "mock")
    get_settings.cache_clear()
    db = get_session()
    try:
        user = _tenant(db)
        upsert_token_account(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            provider="twilio",
            access_token="tenant-twilio-token",
            extra={"account_sid": "ACtenant", "from_number": "+15550001111", "twiml_url": "https://example.test/twiml"},
        )
        upsert_token_account(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            provider="vapi",
            access_token="tenant-vapi-token",
            extra={"assistant_id": "asst-1", "phone_number_id": "pn-1"},
        )
        db.commit()
        provider = compose_voice_provider(db, user.tenant_id, "+15551230000")
        health = provider.health()
        assert isinstance(provider.telephony, TwilioTelephonyProvider)
        assert health.is_mock is False
        assert health.connected is True
        assert resolve_channel(db, user.tenant_id, "twilio").reason == "tenant credential"
    finally:
        for row in db.scalars(select(ProviderAccount).where(ProviderAccount.tenant_id == user.tenant_id, ProviderAccount.provider.in_(["twilio", "vapi"]))).all():
            row.status = "disconnected"
        db.commit()
        db.close()
        monkeypatch.delenv("VOICE_PROVIDER", raising=False)
        get_settings.cache_clear()


def test_openai_live_without_key_is_not_silent_mock(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    try:
        llm = get_llm_provider()
        assert isinstance(llm, NotConfiguredLLMProvider)
        result = llm.complete("hello", system="test")
        assert result.is_mock is False
        assert "NOT_CONFIGURED" in result.text
    finally:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        get_settings.cache_clear()


def test_activate_provisions_tenant_credentials_from_env(client: TestClient, monkeypatch) -> None:
    login(client)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-activate")
    monkeypatch.setenv("OPENAI_DEFAULT_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("DISCOVERY_PROVIDER", "apify")
    monkeypatch.setenv("APIFY_API_TOKEN", "apify-test-activate")
    monkeypatch.setenv("APIFY_ACTOR_ID", "harvestapi/linkedin-profile-search")
    get_settings.cache_clear()
    db = get_session()
    try:
        user = _tenant(db)
        activate_mode(db, tenant_id=user.tenant_id, actor_id=user.id, target="DEMO", reason="full-funnel activate")
        db.commit()
        modes = channel_modes(db, user.tenant_id)
        assert modes["openai"]["mode"] == "LIVE"
        assert modes["openai"]["tenant_credential"] is True
        assert modes["discovery"]["mode"] == "LIVE"
        assert modes["discovery"]["tenant_credential"] is True
        assert isinstance(get_llm_provider(db, user.tenant_id), OpenAILLMProvider)
        assert isinstance(get_lead_discovery_provider(db, user.tenant_id), ApifyLeadDiscoveryProvider)
    finally:
        for row in db.scalars(select(ProviderAccount).where(ProviderAccount.tenant_id == user.tenant_id, ProviderAccount.provider.in_(["openai", "apify"]))).all():
            row.status = "disconnected"
        db.commit()
        db.close()
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_DEFAULT_MODEL", raising=False)
        monkeypatch.delenv("DISCOVERY_PROVIDER", raising=False)
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        monkeypatch.delenv("APIFY_ACTOR_ID", raising=False)
        get_settings.cache_clear()


def test_ensure_route_does_not_rotate_existing_token(client: TestClient) -> None:
    login(client)
    db = get_session()
    try:
        user = _tenant(db)
        original = demo_routing_token("agrayian", "twilio")
        first = ensure_route(db, tenant_id=user.tenant_id, provider="twilio", raw_token=original)
        second = ensure_route(db, tenant_id=user.tenant_id, provider="twilio")
        row = db.scalar(
            select(WebhookRoute).where(
                WebhookRoute.tenant_id == user.tenant_id,
                WebhookRoute.provider == "twilio",
                WebhookRoute.deleted_at.is_(None),
            )
        )
        assert first == original
        assert second == ""
        assert row is not None
        assert row.token_hash == hash_routing_token(original)
    finally:
        db.close()
