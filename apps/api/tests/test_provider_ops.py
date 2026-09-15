from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session
from app.models.identity import User
from app.providers.ads import get_ads_provider
from app.providers.lead_discovery import get_lead_discovery_provider
from app.providers.voice import get_voice_provider
from app.services.provider_ops import (
    CIRCUIT_THRESHOLD,
    begin_action,
    fail_action,
    is_circuit_open,
    record_provider_result,
)
from tests.conftest import login


def test_explicit_live_without_creds_is_not_mock(monkeypatch) -> None:
    monkeypatch.setenv("DISCOVERY_PROVIDER", "apify")
    monkeypatch.setenv("LINKEDIN_ADS_MODE", "live")
    monkeypatch.setenv("VOICE_PROVIDER", "twilio")
    monkeypatch.setenv("APIFY_API_TOKEN", "")
    monkeypatch.setenv("APIFY_ACTOR_ID", "")
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    get_settings.cache_clear()
    try:
        discovery = get_lead_discovery_provider()
        ads = get_ads_provider("linkedin")
        voice = get_voice_provider()
        assert discovery.health()["is_mock"] is False
        assert discovery.health()["connected"] is False
        assert ads.health().is_mock is False
        assert ads.health().connected is False
        assert voice.health().is_mock is False
        assert voice.health().connected is False
    finally:
        monkeypatch.delenv("DISCOVERY_PROVIDER", raising=False)
        monkeypatch.delenv("LINKEDIN_ADS_MODE", raising=False)
        monkeypatch.delenv("VOICE_PROVIDER", raising=False)
        get_settings.cache_clear()


def test_dead_letter_retry_and_cancel(client: TestClient) -> None:

    headers = login(client)
    me = client.get("/api/v1/auth/me", headers=headers).json()["data"]["user"]
    db = get_session()
    try:
        user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
        action = begin_action(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action_type="ads.launch",
            idempotency_key=f"ads.launch.test:{me['tenant_id']}",
            provider="linkedin-ads",
            request_summary="test",
        )
        fail_action(action, failure_class="PERMANENT", error="bad payload", retryable=False)
        db.commit()
        action_id = str(action.id)
    finally:
        db.close()
    listed = client.get("/api/v1/providers/actions", headers=headers, params={"status": "DEAD_LETTER"})
    assert listed.status_code == 200
    assert any(row["id"] == action_id for row in listed.json()["data"])
    retried = client.post(f"/api/v1/providers/actions/{action_id}/retry", headers=headers)
    assert retried.status_code == 200
    cancelled = client.post(f"/api/v1/providers/actions/{action_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "CANCELLED"


def test_circuit_opens_after_consecutive_failures(client: TestClient) -> None:
    login(client)
    db = get_session()
    try:
        user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
        for _ in range(CIRCUIT_THRESHOLD):
            record_provider_result(
                db,
                tenant_id=user.tenant_id,
                actor_id=user.id,
                provider="circuit-test",
                action="ads.launch",
                ok=False,
                failure_class="TRANSIENT",
                error="timeout",
            )
        db.commit()
        assert is_circuit_open(db, tenant_id=user.tenant_id, provider="circuit-test")
    finally:
        db.close()


def test_provider_status_exposes_modes(client: TestClient) -> None:
    headers = login(client)
    status = client.get("/api/v1/autonomy/status", headers=headers)
    assert status.status_code == 200
    providers = status.json()["data"]["providers"]
    names = {row["name"] for row in providers}
    assert {"Apify", "LinkedIn Ads", "Meta Ads", "Voice"} <= names
    for row in providers:
        assert row["mode"] in {"LIVE", "MOCK", "NOT CONNECTED"}
    integrations = client.get("/api/v1/integrations/providers", headers=headers)
    assert integrations.status_code == 200
    assert integrations.json()["data"]
