"""Routes, permissions, the overview, and the worker jobs for the Social Growth Autopilot."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session
from app.models.growth import GrowthAccount, GrowthCalendarItem, GrowthCreative
from app.services.dispatcher import HANDLERS
from app.services.growth import accounts as account_service
from app.services.growth import automation
from tests.conftest import login
from tests.growth_support import approved_brand, approved_strategy, enable_growth, form, user

BASE = "/api/v1/social-growth"


def test_overview_reports_disabled_modes_and_unavailable_evidence(client: TestClient) -> None:
    headers = login(client)
    response = client.get(f"{BASE}/overview", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    capabilities = data["automation"]["capabilities"]
    assert capabilities["publish_mode"] == "disabled" and capabilities["insights_mode"] == "disabled"
    assert capabilities["graph_api_version"] == "v26.0"
    assert data["attribution_30d"]["ga4_status"] == "not_configured"
    assert data["flag_enabled"] is False
    assert data["operating_mode"] in {"DEMO", "PILOT", "PRODUCTION"}
    assert "social.growth_publish" in HANDLERS


def test_account_routes_store_tokens_encrypted_and_enforce_permissions(client: TestClient) -> None:
    admin = login(client, "admin@northline.demo")
    reader = login(client, "readonly@agrayian.demo")
    secret = "EAAG-fixture-token-never-returned-123"
    assert client.post(f"{BASE}/accounts", json={"platform": "facebook", "external_id": "1234567", "access_token": secret}, headers=reader).status_code == 403
    assert client.post(f"{BASE}/accounts", json={"platform": "facebook", "external_id": "page-name", "access_token": secret}, headers=admin).status_code == 422
    assert client.post(f"{BASE}/accounts", json={"platform": "instagram", "external_id": "178414000000", "access_token": secret}, headers=admin).status_code == 422
    created = client.post(f"{BASE}/accounts", json={"platform": "facebook", "external_id": "998877665544", "access_token": secret, "name": "Northline Page"}, headers=admin)
    assert created.status_code == 200 and secret not in created.text
    account = created.json()["data"]["account"]
    assert account["status"] == "unverified" and account["token_expires_at"] == ""
    verify = client.post(f"{BASE}/accounts/{account['id']}/verify", headers=admin)
    assert verify.status_code == 200 and "SOCIAL_GROWTH_INSIGHTS_MODE" in verify.json()["data"]["detail"]
    bad_window = client.patch(f"{BASE}/accounts/{account['id']}", json={"posting_windows": [{"days": [9], "start": "18:00", "end": "09:00"}]}, headers=admin)
    assert bad_window.status_code == 422
    good = client.patch(f"{BASE}/accounts/{account['id']}", json={"posting_windows": [{"days": [0, 2, 4], "start": "08:30", "end": "11:00"}], "daily_cap": 1, "timezone": "Asia/Kolkata"}, headers=admin)
    assert good.status_code == 200 and good.json()["data"]["daily_cap"] == 1
    listed = client.get(f"{BASE}/accounts", headers=admin)
    assert secret not in listed.text and any(row["id"] == account["id"] for row in listed.json()["data"])
    agrayian = login(client)
    assert all(row["id"] != account["id"] for row in client.get(f"{BASE}/accounts", headers=agrayian).json()["data"])
    assert client.post(f"{BASE}/accounts/{account['id']}/verify", headers=agrayian).status_code == 404
    fixture = client.post(f"{BASE}/accounts/fixture", json={"platform": "instagram", "name": "Test grid"}, headers=admin)
    assert fixture.status_code == 200 and fixture.json()["data"]["account"]["provenance"] == "fixture"
    for row in (account, fixture.json()["data"]["account"]):
        assert client.post(f"{BASE}/accounts/{row['id']}/disconnect", headers=admin).json()["data"]["status"] == "disconnected"


def test_approve_routes_need_the_approve_permission(client: TestClient) -> None:
    seller = login(client, "seller@agrayian.demo")
    for path, body in (
        ("/strategy/00000000-0000-0000-0000-000000000001/approve", None),
        ("/creatives/00000000-0000-0000-0000-000000000001/review", {"decision": "approve"}),
        ("/calendar/00000000-0000-0000-0000-000000000001/schedule", None),
        ("/calendar/00000000-0000-0000-0000-000000000001/publish", None),
        ("/grants", {"platform": "instagram", "volume_cap": 2, "days": 7}),
    ):
        assert client.post(f"{BASE}{path}", json=body, headers=seller).status_code == 403, path
    admin = login(client, "admin@northline.demo")
    assert client.post(f"{BASE}/creatives/00000000-0000-0000-0000-000000000001/review", json={"decision": "approve"}, headers=admin).status_code == 404
    assert client.post(f"{BASE}/grants", json={"platform": "tiktok", "volume_cap": 2, "days": 7}, headers=admin).status_code == 422


def test_worker_jobs_follow_the_flag_the_strategy_and_the_modes(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        facts = approved_brand(db, admin.tenant_id, admin)
        account = account_service.create_fixture_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform="instagram", name="IG")
        approved_strategy(db, admin.tenant_id, admin, facts, [account], form(db, admin.tenant_id, admin))
        enable_growth(db, admin.tenant_id, False)
        assert automation.plan_tenant(db, admin.tenant_id) == 0
        enable_growth(db, admin.tenant_id, True)
        planned = automation.plan_tenant(db, admin.tenant_id)
        assert planned > 0
        assert automation.plan_tenant(db, admin.tenant_id) == 0
        produced = automation.prepare_tenant(db, admin.tenant_id, limit=2)
        items = db.scalars(select(GrowthCalendarItem).where(GrowthCalendarItem.tenant_id == admin.tenant_id, GrowthCalendarItem.creative_id.is_not(None))).all()
        assert produced == len(items) <= 2
        creatives = db.scalars(select(GrowthCreative).where(GrowthCreative.tenant_id == admin.tenant_id)).all()
        assert all(row.status in {"draft", "needs_review", "approved"} for row in creatives)
        assert automation.publish_tenant(db, admin.tenant_id) == 0
        assert automation.insights_tenant(db, admin.tenant_id) == 0
        assert automation.ga4_tenant(db, admin.tenant_id) == 0
        runs = automation.automation_runs(db, admin.tenant_id)
        assert {run["kind"] for run in runs} >= {"growth:plan"}
        other = user(db, "admin@northline.demo")
        assert db.scalars(select(GrowthAccount).where(GrowthAccount.tenant_id == other.tenant_id, GrowthAccount.id == account.id)).first() is None
    finally:
        db.rollback()
        db.close()
