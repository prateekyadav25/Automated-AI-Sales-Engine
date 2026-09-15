from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session
from app.models.lifecycle import Campaign
from app.providers.ads import AdsCampaignResult, AdsHealth, AdsMetrics, AdsSpend
from app.services.ads import derived_metrics, sync_campaign
from tests.conftest import login


def test_launch_queues_approval_and_mock_does_not_invent_spend(client: TestClient) -> None:
    headers = login(client)
    created = client.post(
        "/api/v1/lifecycle/campaigns",
        headers=headers,
        json={"name": "LinkedIn hunt", "channel": "linkedin", "objective": "pipeline", "budget": "2500"},
    )
    assert created.status_code == 200
    campaign_id = created.json()["data"]["id"]
    assert created.json()["data"]["spent"] in {"0", "0.00", 0}
    launch = client.post(f"/api/v1/lifecycle/campaigns/{campaign_id}/launch", headers=headers)
    assert launch.status_code == 200, launch.text
    approval_id = launch.json()["data"]["approval_id"]
    decided = client.post(
        f"/api/v1/ai/approvals/{approval_id}/decide",
        headers=headers,
        json={"decision": "approve", "note": "Try launch"},
    )
    assert decided.status_code == 200
    note = decided.json()["data"]["decision_note"]
    assert "invented" in note.lower() or "not launched" in note.lower() or "no live" in note.lower()
    detail = client.get(f"/api/v1/lifecycle/campaigns/{campaign_id}", headers=headers).json()["data"]
    assert detail["status"] != "launched"
    assert Decimal(str(detail["spent"])) == Decimal("0")


class LiveAdsStub:
    def __init__(self) -> None:
        self.launches = 0

    def health(self) -> AdsHealth:
        return AdsHealth(provider="linkedin-ads", is_mock=False, connected=True, reason="stub")

    def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult:
        self.launches += 1
        return AdsCampaignResult(ok=True, provider="linkedin-ads", is_mock=False, external_id="urn:li:sponsoredCampaign:99", provider_status="ACTIVE")

    def pause_campaign(self, *, external_id: str) -> AdsCampaignResult:
        return AdsCampaignResult(ok=True, provider="linkedin-ads", is_mock=False, external_id=external_id, provider_status="PAUSED")

    def get_status(self, *, external_id: str) -> AdsCampaignResult:
        return AdsCampaignResult(ok=True, provider="linkedin-ads", is_mock=False, external_id=external_id, provider_status="ACTIVE")

    def get_spend(self, *, external_id: str) -> AdsSpend:
        return AdsSpend(amount=Decimal("12.50"), currency="USD", provider="linkedin-ads", is_mock=False, reason="")

    def get_metrics(self, *, external_id: str) -> AdsMetrics:
        return AdsMetrics(
            spend=Decimal("12.50"),
            impressions=1000,
            clicks=25,
            conversions=2,
            currency="USD",
            provider="linkedin-ads",
            is_mock=False,
            provider_status="ACTIVE",
        )


def test_budget_exceeded_blocks_launch(client: TestClient) -> None:
    headers = login(client)
    client.patch("/api/v1/autonomy/settings", headers=headers, json={"daily_budget_limit": 100})
    created = client.post(
        "/api/v1/lifecycle/campaigns",
        headers=headers,
        json={"name": "Over budget", "channel": "linkedin", "budget": "250"},
    )
    launch = client.post(f"/api/v1/lifecycle/campaigns/{created.json()['data']['id']}/launch", headers=headers)
    assert launch.status_code == 409
    client.patch("/api/v1/autonomy/settings", headers=headers, json={"daily_budget_limit": 0})


def test_successful_launch_and_idempotent_retry(client: TestClient, monkeypatch) -> None:
    stub = LiveAdsStub()
    monkeypatch.setattr("app.services.ads.get_ads_provider", lambda channel, *args, **kwargs: stub)
    headers = login(client)
    created = client.post(
        "/api/v1/lifecycle/campaigns",
        headers=headers,
        json={"name": "Live hunt", "channel": "linkedin", "objective": "pipeline", "budget": "500"},
    )
    campaign_id = created.json()["data"]["id"]
    launch = client.post(f"/api/v1/lifecycle/campaigns/{campaign_id}/launch", headers=headers)
    assert launch.status_code == 200, launch.text
    approval_id = launch.json()["data"]["approval_id"]
    first = client.post(f"/api/v1/ai/approvals/{approval_id}/decide", headers=headers, json={"decision": "approve", "note": "go"})
    assert first.status_code == 200
    second = client.post(f"/api/v1/ai/approvals/{approval_id}/decide", headers=headers, json={"decision": "approve", "note": "again"})
    assert second.status_code == 200
    assert stub.launches == 1
    detail = client.get(f"/api/v1/lifecycle/campaigns/{campaign_id}", headers=headers).json()["data"]
    assert detail["status"] == "launched"
    assert detail["external_campaign_id"] == "urn:li:sponsoredCampaign:99"


def test_provider_error_does_not_mark_launched(client: TestClient, monkeypatch) -> None:
    class BrokenAds(LiveAdsStub):
        def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn refused", failure_class="PERMANENT")

    monkeypatch.setattr("app.services.ads.get_ads_provider", lambda channel, *args, **kwargs: BrokenAds())
    headers = login(client)
    created = client.post(
        "/api/v1/lifecycle/campaigns",
        headers=headers,
        json={"name": "Broken", "channel": "linkedin", "budget": "200"},
    )
    campaign_id = created.json()["data"]["id"]
    launch = client.post(f"/api/v1/lifecycle/campaigns/{campaign_id}/launch", headers=headers)
    client.post(f"/api/v1/ai/approvals/{launch.json()['data']['approval_id']}/decide", headers=headers, json={"decision": "approve", "note": "try"})
    detail = client.get(f"/api/v1/lifecycle/campaigns/{campaign_id}", headers=headers).json()["data"]
    assert detail["status"] != "launched"
    assert not detail["external_campaign_id"]


def test_metric_normalization_requires_inputs() -> None:
    partial = AdsMetrics(spend=Decimal("10"), impressions=None, clicks=None, conversions=None, currency="USD", provider="linkedin-ads", is_mock=False)
    derived = derived_metrics(partial)
    assert derived["ctr"] is None
    assert derived["cpc"] is None
    full = AdsMetrics(spend=Decimal("10"), impressions=100, clicks=10, conversions=2, currency="USD", provider="linkedin-ads", is_mock=False)
    ready = derived_metrics(full)
    assert ready["ctr"] == Decimal("0.1")
    assert ready["cpc"] == Decimal("1")


def test_status_sync_uses_provider_metrics(client: TestClient, monkeypatch) -> None:
    stub = LiveAdsStub()
    monkeypatch.setattr("app.services.ads.get_ads_provider", lambda channel, *args, **kwargs: stub)
    headers = login(client)
    created = client.post(
        "/api/v1/lifecycle/campaigns",
        headers=headers,
        json={"name": "Sync me", "channel": "linkedin", "budget": "200"},
    )
    campaign_id = created.json()["data"]["id"]
    launch = client.post(f"/api/v1/lifecycle/campaigns/{campaign_id}/launch", headers=headers)
    client.post(f"/api/v1/ai/approvals/{launch.json()['data']['approval_id']}/decide", headers=headers, json={"decision": "approve", "note": "go"})
    db = get_session()
    try:
        row = db.scalar(select(Campaign).where(Campaign.id == UUID(campaign_id)))
        assert row is not None
        sync_campaign(db, tenant_id=row.tenant_id, actor_id=row.created_by, campaign=row)
        db.commit()
        assert row.impressions == 1000
        assert row.clicks == 25
        assert row.spent == Decimal("12.50")
    finally:
        db.close()


def test_outbound_campaign_cannot_launch(client: TestClient) -> None:
    headers = login(client)
    created = client.post(
        "/api/v1/lifecycle/campaigns",
        headers=headers,
        json={"name": "Outbound only", "channel": "outbound", "budget": "100"},
    )
    campaign_id = created.json()["data"]["id"]
    launch = client.post(f"/api/v1/lifecycle/campaigns/{campaign_id}/launch", headers=headers)
    assert launch.status_code == 409
