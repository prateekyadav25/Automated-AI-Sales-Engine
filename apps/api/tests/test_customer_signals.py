import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session
from app.models.autonomy import AutopilotSettings
from app.models.crm import Customer
from app.models.identity import User
from app.models.lifecycle import HealthScore
from app.models.post_sale import Contract, ContractLine, CustomerRisk, ExpansionRecommendation
from app.models.signals import UsageEvent, UsageRollup
from app.services.advocacy import evaluate_advocacy
from app.services.customer_health import recalculate
from app.services.webhook_routes import demo_routing_token
from tests.conftest import login


def _sign(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    secret = get_settings().integrations_webhook_secret or get_settings().secret_key
    return body, hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post_hook(client: TestClient, provider: str, payload: dict, token: str | None = None, signature: str | None = None):
    body, computed = _sign(payload)
    raw = token or demo_routing_token("agrayian", provider)
    return client.post(
        f"/api/v1/webhooks/{provider}/{raw}",
        headers={"X-Webhook-Signature": signature if signature is not None else computed, "Content-Type": "application/json"},
        content=body,
    )


def _close(client: TestClient, headers: dict, name: str, domain: str = "") -> dict:
    account = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"name": name, "industry": "bfsi", "domain": domain or f"{name.lower().replace(' ', '')}.example"},
    ).json()["data"]
    opp = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": account["id"], "name": f"{name} Deal", "stage": "commit", "amount": "90000", "probability": 90},
    ).json()["data"]
    won = client.post(f"/api/v1/opportunities/{opp['id']}/close-won", headers=headers)
    assert won.status_code == 200, won.text
    customer = won.json()["data"]
    return {"account": account, "customer": customer}


def test_usage_live_event_and_duplicate(client: TestClient) -> None:
    headers = login(client)
    client.patch("/api/v1/autonomy/settings", headers=headers, json={"enabled": True, "customer_health_enabled": True})
    closed = _close(client, headers, "Signal Usage Live")
    domain = closed["account"]["domain"]
    payload = {
        "external_id": "use-1",
        "event_type": "user.active",
        "domain": domain,
        "user_id": "u1",
        "observed_at": datetime.now(UTC).isoformat(),
    }
    first = _post_hook(client, "usage", payload)
    assert first.status_code == 200, first.text
    second = _post_hook(client, "usage", payload)
    assert second.status_code == 200
    db = get_session()
    try:
        count = len(db.scalars(select(UsageEvent).where(UsageEvent.external_id == "use-1")).all())
        assert count == 1
        health = db.scalar(select(HealthScore).where(HealthScore.customer_id == UUID(closed["customer"]["id"])))
        assert health is not None
        assert health.version == "rules-v2"
        components = json.loads(health.components_json)
        assert components["usage"]["status"] == "LIVE"
        assert "usage" not in (health.unavailable_components or "")
    finally:
        db.close()
    detail = client.get(f"/api/v1/post-sale/customers/{closed['customer']['id']}", headers=headers).json()["data"]
    assert detail["usage_freshness"] == "LIVE"
    assert detail["health_version"] == "rules-v2"


def test_usage_bad_signature_and_wrong_tenant(client: TestClient) -> None:
    payload = {"external_id": "bad-1", "event_type": "user.active", "domain": "x.example"}
    bad = _post_hook(client, "usage", payload, signature="deadbeef")
    assert bad.status_code == 401
    other = _post_hook(client, "usage", payload, token=demo_routing_token("northline", "usage"))
    assert other.status_code == 200
    db = get_session()
    try:
        rows = db.scalars(select(UsageEvent).where(UsageEvent.external_id == "bad-1")).all()
        assert all(str(row.tenant_id) != "" for row in rows)
    finally:
        db.close()


def test_stale_usage_excluded_from_score(client: TestClient) -> None:
    headers = login(client)
    client.patch(
        "/api/v1/autonomy/settings",
        headers=headers,
        json={"enabled": True, "customer_health_enabled": True, "usage_freshness_hours": 24},
    )
    closed = _close(client, headers, "Signal Stale Usage")
    domain = closed["account"]["domain"]
    _post_hook(
        client,
        "usage",
        {
            "external_id": "stale-1",
            "event_type": "user.active",
            "domain": domain,
            "user_id": "u-stale",
            "observed_at": datetime.now(UTC).isoformat(),
        },
    )
    db = get_session()
    try:
        customer = db.get(Customer, UUID(closed["customer"]["id"]))
        rollup = db.scalar(select(UsageRollup).where(UsageRollup.customer_id == customer.id))
        assert rollup is not None
        rollup.last_activity_at = datetime.now(UTC) - timedelta(days=10)
        db.commit()
        recalculate(db, customer.tenant_id, customer, customer.created_by)
        db.commit()
        health = db.scalar(select(HealthScore).where(HealthScore.customer_id == customer.id))
        components = json.loads(health.components_json)
        assert components["usage"]["status"] == "STALE"
        assert "usage" in health.unavailable_components
    finally:
        db.close()


def test_high_and_low_utilization(client: TestClient) -> None:
    headers = login(client)
    client.patch(
        "/api/v1/autonomy/settings",
        headers=headers,
        json={"enabled": True, "customer_health_enabled": True, "upsell_enabled": True, "expansion_auto_opportunity_enabled": False},
    )
    closed = _close(client, headers, "Signal Seats")
    domain = closed["account"]["domain"]
    db = get_session()
    try:
        contract = db.scalar(select(Contract).where(Contract.customer_id == UUID(closed["customer"]["id"])))
        assert contract is not None
        db.add(ContractLine(tenant_id=contract.tenant_id, contract_id=contract.id, description="Seats", quantity=10))
        db.commit()
    finally:
        db.close()
    for index in range(9):
        _post_hook(
            client,
            "usage",
            {
                "external_id": f"seat-{index}",
                "event_type": "seat.active",
                "domain": domain,
                "user_id": f"seat-user-{index}",
            },
        )
    recs = client.get("/api/v1/post-sale/expansion", headers=headers).json()["data"]
    mine = [row for row in recs if row["customer_id"] == closed["customer"]["id"] and row["kind"] == "upsell"]
    assert mine
    assert all(row["opportunity_id"] is None for row in mine)
    opps = client.get("/api/v1/opportunities", headers=headers).json()["data"]
    assert not any(row["name"] == "Seat saturation" for row in opps)

    low = _close(client, headers, "Signal Low Adopt")
    db = get_session()
    try:
        contract = db.scalar(select(Contract).where(Contract.customer_id == UUID(low["customer"]["id"])))
        db.add(ContractLine(tenant_id=contract.tenant_id, contract_id=contract.id, description="Seats", quantity=20))
        db.commit()
    finally:
        db.close()
    _post_hook(
        client,
        "usage",
        {"external_id": "low-1", "event_type": "seat.active", "domain": low["account"]["domain"], "user_id": "only-one"},
    )
    detail = client.get(f"/api/v1/post-sale/customers/{low['customer']['id']}", headers=headers).json()["data"]
    assert any(row["risk_type"] == "ADOPTION_RISK" for row in detail["risks"])
    recs = client.get("/api/v1/post-sale/expansion", headers=headers).json()["data"]
    assert not [row for row in recs if row["customer_id"] == low["customer"]["id"] and row["kind"] == "upsell"]


def test_support_critical_resolve_and_stale(client: TestClient) -> None:
    headers = login(client)
    client.patch("/api/v1/autonomy/settings", headers=headers, json={"enabled": True, "customer_health_enabled": True, "customer_success_enabled": True})
    closed = _close(client, headers, "Signal Support")
    domain = closed["account"]["domain"]
    created = _post_hook(
        client,
        "support",
        {
            "external_id": "tix-1",
            "event_type": "ticket.created",
            "ticket_id": "tix-1",
            "domain": domain,
            "severity": "critical",
            "status": "open",
        },
    )
    assert created.status_code == 200, created.text
    dup = _post_hook(
        client,
        "support",
        {"external_id": "tix-1", "event_type": "ticket.created", "ticket_id": "tix-1", "domain": domain, "severity": "critical"},
    )
    assert dup.status_code == 200
    detail = client.get(f"/api/v1/post-sale/customers/{closed['customer']['id']}", headers=headers).json()["data"]
    assert any(row["risk_type"] == "SUPPORT_RISK" for row in detail["risks"])
    _post_hook(
        client,
        "support",
        {"external_id": "tix-1-close", "event_type": "ticket.resolved", "ticket_id": "tix-1", "domain": domain},
    )
    db = get_session()
    try:
        health = db.scalar(select(HealthScore).where(HealthScore.customer_id == UUID(closed["customer"]["id"])))
        components = json.loads(health.components_json)
        assert components["support"]["status"] in {"LIVE", "STALE"}
    finally:
        db.close()


def test_finance_overdue_payment_mismatch(client: TestClient) -> None:
    headers = login(client)
    client.patch("/api/v1/autonomy/settings", headers=headers, json={"enabled": True, "customer_health_enabled": True})
    closed = _close(client, headers, "Signal Finance")
    domain = closed["account"]["domain"]
    overdue = _post_hook(
        client,
        "finance",
        {
            "external_id": "inv-1",
            "event_type": "invoice.overdue",
            "invoice_id": "inv-1",
            "domain": domain,
            "amount": "1200",
            "currency": "INR",
            "days_past_due": 18,
            "contract_value": "1",
        },
    )
    assert overdue.status_code == 200, overdue.text
    dup = _post_hook(
        client,
        "finance",
        {"external_id": "inv-1", "event_type": "invoice.created", "invoice_id": "inv-1", "domain": domain},
    )
    assert dup.status_code == 200
    detail = client.get(f"/api/v1/post-sale/customers/{closed['customer']['id']}", headers=headers).json()["data"]
    assert any(row["risk_type"] == "COMMERCIAL_RISK" for row in detail["risks"])
    tasks = client.get("/api/v1/tasks", headers=headers, params={"q": "mismatch"}).json()["data"]
    assert any(row["entity_id"] == closed["customer"]["id"] for row in tasks)
    _post_hook(
        client,
        "finance",
        {"external_id": "pay-1", "event_type": "payment.received", "invoice_id": "inv-1", "domain": domain, "amount": "1200"},
    )


def test_health_mock_excluded_and_coverage(client: TestClient) -> None:
    headers = login(client)
    closed = _close(client, headers, "Signal Coverage")
    detail = client.get(f"/api/v1/post-sale/customers/{closed['customer']['id']}", headers=headers).json()["data"]
    assert detail["health_version"] == "rules-v2"
    assert "usage" in (detail.get("unavailable_components") or "")
    assert detail["health_data_coverage"] > 0
    assert detail["health_data_coverage"] < 100
    assert detail["usage_freshness"] == "MOCK"


def test_mapping_confirm_and_advocacy_block(client: TestClient) -> None:
    headers = login(client)
    client.patch("/api/v1/autonomy/settings", headers=headers, json={"enabled": True, "advocacy_enabled": True, "customer_health_enabled": True})
    closed = _close(client, headers, "Signal Mapping Co")
    _post_hook(
        client,
        "usage",
        {
            "external_id": "map-1",
            "event_type": "user.active",
            "account_name": "Signal Mapping Co",
            "account_external_id": "ext-map-1",
            "user_id": "mapper",
        },
    )
    pending = client.get("/api/v1/integrations/mappings", headers=headers).json()["data"]
    mine = [row for row in pending if row["external_id"] == "ext-map-1"]
    assert mine
    assert mine[0]["status"] == "pending"
    confirmed = client.post(f"/api/v1/integrations/mappings/{mine[0]['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "confirmed"
    live = _post_hook(
        client,
        "usage",
        {"external_id": "map-2", "event_type": "user.active", "account_external_id": "ext-map-1", "user_id": "mapper-2"},
    )
    assert live.status_code == 200
    _post_hook(
        client,
        "support",
        {
            "external_id": "crit-adv",
            "event_type": "ticket.created",
            "ticket_id": "crit-adv",
            "account_external_id": "ext-map-1",
            "severity": "critical",
        },
    )
    db = get_session()
    try:
        customer = db.get(Customer, UUID(closed["customer"]["id"]))
        customer.lifecycle_state = "ACTIVE"
        customer.onboarding_completed_at = datetime.now(UTC)
        health = db.scalar(select(HealthScore).where(HealthScore.customer_id == customer.id))
        health.total = 88
        settings = db.scalar(select(AutopilotSettings).where(AutopilotSettings.tenant_id == customer.tenant_id))
        actor = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
        asset = evaluate_advocacy(db, tenant_id=customer.tenant_id, actor_id=actor.id, customer=customer, settings=settings)
        db.commit()
        assert asset is None
    finally:
        db.close()


def test_no_evidence_no_expansion(client: TestClient) -> None:
    headers = login(client)
    closed = _close(client, headers, "Signal No Evidence")
    db = get_session()
    try:
        recs = db.scalars(
            select(ExpansionRecommendation).where(
                ExpansionRecommendation.customer_id == UUID(closed["customer"]["id"]),
                ExpansionRecommendation.kind == "upsell",
            )
        ).all()
        assert recs == []
        risks = db.scalars(
            select(CustomerRisk).where(
                CustomerRisk.customer_id == UUID(closed["customer"]["id"]),
                CustomerRisk.risk_type == "ADOPTION_RISK",
            )
        ).all()
        assert risks == []
    finally:
        db.close()
