from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.session import get_session
from app.models.autonomy import AutopilotSettings
from app.models.crm import Customer, NextBestAction, Renewal
from app.models.identity import User
from app.models.lifecycle import AdvocacyAsset, HealthScore, OnboardingMilestone, OnboardingPlan
from app.models.post_sale import Contract, CustomerRisk, ExpansionRecommendation, HandoffPackage
from app.services.advocacy import evaluate_advocacy
from tests.conftest import login


def _enable(client: TestClient, headers: dict) -> None:
    response = client.patch(
        "/api/v1/autonomy/settings",
        headers=headers,
        json={
            "enabled": True,
            "customer_health_enabled": True,
            "renewal_enabled": True,
            "expansion_enabled": True,
            "advocacy_enabled": True,
            "customer_success_enabled": True,
            "upsell_enabled": True,
            "cross_sell_enabled": True,
            "expansion_auto_opportunity_enabled": False,
            "minimum_expansion_confidence": 40,
        },
    )
    assert response.status_code == 200, response.text


def _cycle(client: TestClient, headers: dict) -> None:
    response = client.post("/api/v1/autonomy/runs", headers=headers, json={})
    assert response.status_code == 200, response.text


def _close_new(client: TestClient, headers: dict, name: str) -> tuple[dict, dict, dict]:
    account = client.post("/api/v1/accounts", headers=headers, json={"name": name, "industry": "bfsi"}).json()["data"]
    created = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={
            "account_id": account["id"],
            "name": f"{name} Deal",
            "stage": "commit",
            "amount": "120000",
            "probability": 90,
        },
    )
    assert created.status_code == 200, created.text
    opp = created.json()["data"]
    won = client.post(f"/api/v1/opportunities/{opp['id']}/close-won", headers=headers)
    assert won.status_code == 200, won.text
    return account, opp, won.json()["data"]


def _counts(customer_id: str) -> dict[str, int]:
    db = get_session()
    try:
        cid = UUID(customer_id)
        return {
            "customers": int(db.scalar(select(func.count()).where(Customer.id == cid)) or 0),
            "renewals": int(db.scalar(select(func.count()).where(Renewal.customer_id == cid, Renewal.deleted_at.is_(None))) or 0),
            "handoffs": int(db.scalar(select(func.count()).where(HandoffPackage.customer_id == cid)) or 0),
            "contracts": int(db.scalar(select(func.count()).where(Contract.customer_id == cid, Contract.deleted_at.is_(None))) or 0),
            "risks": int(db.scalar(select(func.count()).where(CustomerRisk.customer_id == cid, CustomerRisk.deleted_at.is_(None))) or 0),
            "expansion": int(
                db.scalar(select(func.count()).where(ExpansionRecommendation.customer_id == cid, ExpansionRecommendation.deleted_at.is_(None))) or 0
            ),
            "advocacy": int(db.scalar(select(func.count()).where(AdvocacyAsset.customer_id == cid, AdvocacyAsset.deleted_at.is_(None))) or 0),
        }
    finally:
        db.close()


def test_journey_1_close_won_activation_is_idempotent(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    _account, opp, customer = _close_new(client, headers, "Journey One")
    first = client.get(f"/api/v1/post-sale/customers/{customer['id']}", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()["data"]
    assert body["handoff"] is not None
    assert body["onboarding_status"]
    assert len(body["milestones"]) == 8
    assert body["renewal_date"]
    assert body["health_version"] == "rules-v2"
    assert "usage" in (body.get("unavailable_components") or "")
    before = _counts(customer["id"])
    again = client.post(f"/api/v1/opportunities/{opp['id']}/close-won", headers=headers)
    assert again.status_code == 200
    after = _counts(customer["id"])
    assert after == before
    customers = client.get("/api/v1/customers", headers=headers).json()["data"]
    assert len([row for row in customers if row["opportunity_id"] == opp["id"]]) == 1


def test_journey_2_overdue_milestone_raises_risk_and_nba(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    _account, _opp, customer = _close_new(client, headers, "Journey Two")
    db = get_session()
    try:
        plan = db.scalar(select(OnboardingPlan).where(OnboardingPlan.customer_id == UUID(customer["id"])))
        assert plan is not None
        milestone = db.scalar(select(OnboardingMilestone).where(OnboardingMilestone.plan_id == plan.id).order_by(OnboardingMilestone.position.asc()))
        assert milestone is not None
        milestone.due_date = date.today() - timedelta(days=2)
        db.commit()
    finally:
        db.close()
    _cycle(client, headers)
    _cycle(client, headers)
    detail = client.get(f"/api/v1/post-sale/customers/{customer['id']}", headers=headers).json()["data"]
    assert any(row["risk_type"] == "onboarding_delay" for row in detail["risks"])
    db = get_session()
    try:
        nba = db.scalar(
            select(NextBestAction)
            .where(NextBestAction.entity_type == "customer", NextBestAction.entity_id == customer["id"])
            .order_by(NextBestAction.created_at.desc())
        )
        assert nba is not None
        tasks = client.get("/api/v1/tasks", headers=headers, params={"q": "delay"}).json()["data"]
        assert any(
            row["entity_id"] == customer["id"] and ("delay" in row["title"].lower() or "onboarding" in row["title"].lower())
            for row in tasks
        )
    finally:
        db.close()


def test_journey_3_health_decline_queues_cs_approval(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    _account, _opp, customer = _close_new(client, headers, "Journey Three")
    db = get_session()
    try:
        health = db.scalar(select(HealthScore).where(HealthScore.customer_id == UUID(customer["id"])))
        assert health is not None
        health.trend = "declining"
        health.total = 28
        db.commit()
    finally:
        db.close()
    _cycle(client, headers)
    _cycle(client, headers)
    approvals = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    mine = [row for row in approvals if row.get("entity_id") == customer["id"] and row["action_type"] == "customer.success.send"]
    assert mine
    assert mine[0]["category"] == "CUSTOMER SUCCESS"
    first_id = mine[0]["id"]
    _cycle(client, headers)
    again = [row for row in client.get("/api/v1/ai/approvals", headers=headers).json()["data"] if row.get("entity_id") == customer["id"] and row["action_type"] == "customer.success.send"]
    assert len(again) == 1
    assert again[0]["id"] == first_id


def test_journey_4_renewal_window_prepares_approval(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    _account, _opp, customer = _close_new(client, headers, "Journey Four")
    db = get_session()
    try:
        renewal = db.scalar(select(Renewal).where(Renewal.customer_id == UUID(customer["id"]), Renewal.deleted_at.is_(None)))
        assert renewal is not None
        renewal.renewal_date = date.today() + timedelta(days=90)
        db.commit()
        renewal_id = str(renewal.id)
    finally:
        db.close()
    _cycle(client, headers)
    _cycle(client, headers)
    approvals = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    mine = [row for row in approvals if row.get("entity_id") == renewal_id and row["action_type"] == "renewal.commercial"]
    assert mine
    assert mine[0]["category"] == "RENEWAL"
    payload = mine[0].get("payload_json") or ""
    assert "needs_review" in payload or "baseline" in payload
    _cycle(client, headers)
    again = [row for row in client.get("/api/v1/ai/approvals", headers=headers).json()["data"] if row.get("entity_id") == renewal_id and row["action_type"] == "renewal.commercial"]
    assert len(again) == 1


def test_journey_5_expansion_recommendation_has_null_amount(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    account, _opp, customer = _close_new(client, headers, "Journey Five")
    before = client.get("/api/v1/opportunities", headers=headers).json()["data"]
    before_ids = {row["id"] for row in before if row["account_id"] == account["id"]}
    _cycle(client, headers)
    recs = client.get("/api/v1/post-sale/expansion", headers=headers).json()["data"]
    mine = [row for row in recs if row["customer_id"] == customer["id"]]
    assert mine
    assert all(row["amount"] is None for row in mine)
    assert all(row["opportunity_id"] is None for row in mine)
    after = client.get("/api/v1/opportunities", headers=headers).json()["data"]
    after_ids = {row["id"] for row in after if row["account_id"] == account["id"]}
    assert after_ids == before_ids
    _cycle(client, headers)
    again = [row for row in client.get("/api/v1/post-sale/expansion", headers=headers).json()["data"] if row["customer_id"] == customer["id"]]
    assert len(again) == len(mine)


def test_journey_6_advocacy_quote_stays_null(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    account, _opp, customer = _close_new(client, headers, "Journey Six")
    db = get_session()
    try:
        row = db.get(Customer, UUID(customer["id"]))
        assert row is not None
        row.lifecycle_state = "ACTIVE"
        row.onboarding_completed_at = datetime.now(UTC)
        row.health_trend = "improving"
        health = db.scalar(select(HealthScore).where(HealthScore.customer_id == row.id))
        assert health is not None
        health.total = 82
        health.trend = "improving"
        for risk in db.scalars(select(CustomerRisk).where(CustomerRisk.customer_id == row.id, CustomerRisk.status == "open")).all():
            risk.status = "resolved"
        settings = db.scalar(select(AutopilotSettings).where(AutopilotSettings.tenant_id == row.tenant_id, AutopilotSettings.deleted_at.is_(None)))
        actor = db.scalar(select(User).where(User.tenant_id == row.tenant_id, User.email == "admin@agrayian.demo"))
        assert settings is not None and actor is not None
        first = evaluate_advocacy(db, tenant_id=row.tenant_id, actor_id=actor.id, customer=row, settings=settings)
        second = evaluate_advocacy(db, tenant_id=row.tenant_id, actor_id=actor.id, customer=row, settings=settings)
        db.commit()
        assert first is not None
        assert first.quote is None
        assert second is not None
        assert first.id == second.id
    finally:
        db.close()
    assets = client.get("/api/v1/lifecycle/advocacy", headers=headers).json()["data"]["assets"]
    mine = [row for row in assets if row.get("customer_id") == customer["id"]]
    assert mine
    assert mine[0]["quote"] is None
    approvals = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    asks = [row for row in approvals if row.get("entity_id") == customer["id"] and row["action_type"] == "advocacy.request.send"]
    assert len(asks) == 1
    referred = client.post(
        "/api/v1/lifecycle/advocacy/referrals",
        headers=headers,
        json={"referrer_account_id": account["id"], "referred_name": "Pat Referral", "email": "pat.referral@example.com"},
    )
    assert referred.status_code == 200, referred.text
    ingested = client.post(f"/api/v1/post-sale/referrals/{referred.json()['data']['id']}/ingest", headers=headers)
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()["data"]["consent_email"] is False
    lead = client.get(f"/api/v1/leads/{ingested.json()['data']['lead_id']}", headers=headers).json()["data"]
    assert lead["source"] == "referral"
    assert lead["consent_email"] is False


def test_journey_7_retry_does_not_duplicate_post_sale(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    _account, opp, customer = _close_new(client, headers, "Journey Seven")
    db = get_session()
    try:
        plan = db.scalar(select(OnboardingPlan).where(OnboardingPlan.customer_id == UUID(customer["id"])))
        milestone = db.scalar(select(OnboardingMilestone).where(OnboardingMilestone.plan_id == plan.id))
        milestone.due_date = date.today() - timedelta(days=3)
        renewal = db.scalar(select(Renewal).where(Renewal.customer_id == UUID(customer["id"])))
        renewal.renewal_date = date.today() + timedelta(days=90)
        db.commit()
    finally:
        db.close()
    _cycle(client, headers)
    _cycle(client, headers)
    snapshot = _counts(customer["id"])
    client.post(f"/api/v1/opportunities/{opp['id']}/close-won", headers=headers)
    _cycle(client, headers)
    _cycle(client, headers)
    assert _counts(customer["id"]) == snapshot


def test_cross_tenant_post_sale_404(client: TestClient) -> None:
    agrayian = login(client)
    northline = login(client, "admin@northline.demo")
    _enable(client, agrayian)
    _account, _opp, customer = _close_new(client, agrayian, "Isolation Customer")
    assert client.get(f"/api/v1/customers/{customer['id']}", headers=northline).status_code == 404
    assert client.get(f"/api/v1/post-sale/customers/{customer['id']}", headers=northline).status_code == 404
    assert client.post(f"/api/v1/lifecycle/success/health/{customer['id']}", headers=northline).status_code == 404
    success = client.get("/api/v1/lifecycle/success", headers=northline).json()["data"]
    assert all(row["customer"]["id"] != customer["id"] for row in success)
    renewals = client.get("/api/v1/lifecycle/renewals", headers=northline).json()["data"]
    assert all(row.get("customer_id") != customer["id"] for row in renewals)
    expansion = client.get("/api/v1/post-sale/expansion", headers=northline).json()["data"]
    assert all(row["customer_id"] != customer["id"] for row in expansion)
    advocacy = client.get("/api/v1/lifecycle/advocacy", headers=northline).json()["data"]
    assert all(row.get("customer_id") != customer["id"] for row in advocacy["assets"])
    attention = client.get("/api/v1/post-sale/attention", headers=agrayian)
    assert attention.status_code == 200
    lanes = client.get("/api/v1/post-sale/lanes", headers=agrayian)
    assert lanes.status_code == 200
    assert {row["lane"] for row in lanes.json()["data"]} == {"ACQUIRE", "SELL", "SUCCEED", "RETAIN", "GROW", "ADVOCATE"}
