from decimal import Decimal

from fastapi.testclient import TestClient

from app.services.lifecycle import quote_totals
from tests.conftest import login


def test_quote_totals_are_deterministic() -> None:
    discounted, total, approval = quote_totals(Decimal("1000"), 10, 0)
    assert discounted == Decimal("900.00")
    assert total == Decimal("900.00")
    assert approval is True
    _discounted, taxed, no_approval = quote_totals(Decimal("1000"), 0, 10)
    assert taxed == Decimal("1100.00")
    assert no_approval is False


def test_campaigns_are_tenant_scoped(client: TestClient) -> None:
    agrayian = login(client, "admin@agrayian.demo")
    northline = login(client, "admin@northline.demo")
    created = client.post(
        "/api/v1/lifecycle/campaigns",
        headers=agrayian,
        json={"name": "Secret ABM", "channel": "abm", "objective": "pipeline"},
    )
    assert created.status_code == 200, created.text
    campaign_id = created.json()["data"]["id"]
    leaked = client.get(f"/api/v1/lifecycle/campaigns/{campaign_id}", headers=northline)
    assert leaked.status_code == 404


def test_sequence_enroll_does_not_send_and_honors_opt_out(client: TestClient) -> None:
    headers = login(client)
    sequences = client.get("/api/v1/lifecycle/sequences", headers=headers)
    assert sequences.status_code == 200
    sequence_id = sequences.json()["data"][0]["id"]
    leads = client.get("/api/v1/leads", headers=headers).json()["data"]
    consented = next(row for row in leads if row["consent_email"] and not row["opt_out"])
    enrolled = client.post(
        f"/api/v1/lifecycle/sequences/{sequence_id}/enroll",
        headers=headers,
        json={"lead_id": consented["id"]},
    )
    assert enrolled.status_code == 200, enrolled.text
    approvals = client.get("/api/v1/ai/approvals", headers=headers)
    assert approvals.status_code == 200
    titles = [row["title"] for row in approvals.json()["data"]]
    assert any("sequence" in title.lower() for title in titles)

    blocked_lead = client.post(
        "/api/v1/leads",
        headers=headers,
        json={
            "first_name": "No",
            "last_name": "Outreach",
            "email": "no.outreach@example.com",
            "company_name": "Opt Out Co",
            "opt_out": True,
            "consent_email": False,
        },
    )
    assert blocked_lead.status_code == 200
    denied = client.post(
        f"/api/v1/lifecycle/sequences/{sequence_id}/enroll",
        headers=headers,
        json={"lead_id": blocked_lead.json()["data"]["id"]},
    )
    assert denied.status_code == 409


def test_conversation_requires_consent(client: TestClient) -> None:
    headers = login(client)
    denied = client.post(
        "/api/v1/lifecycle/conversations",
        headers=headers,
        json={"channel": "voice", "subject": "Cold call", "consent": False, "transcript": "no"},
    )
    assert denied.status_code == 409
    ok = client.post(
        "/api/v1/lifecycle/conversations",
        headers=headers,
        json={"channel": "chat", "subject": "Consented chat", "consent": True, "transcript": "hello"},
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["is_mock"] is False


def test_quote_math_and_discount_approval(client: TestClient) -> None:
    headers = login(client)
    products = client.get("/api/v1/lifecycle/products", headers=headers).json()["data"]
    opps = client.get("/api/v1/opportunities", headers=headers).json()["data"]
    open_opp = next(row for row in opps if row["stage"] not in {"closed_won", "closed_lost"})
    created = client.post(
        "/api/v1/lifecycle/quotes",
        headers=headers,
        json={
            "opportunity_id": open_opp["id"],
            "discount_pct": 12,
            "tax_pct": 0,
            "lines": [{"product_id": products[0]["id"], "quantity": 2, "unit_price": "100"}],
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()["data"]
    assert Decimal(str(body["subtotal"])) == Decimal("200.00")
    assert Decimal(str(body["total"])) == Decimal("176.00")
    assert body["approval_required"] is True


def test_forecast_and_playbook_persist(client: TestClient) -> None:
    headers = login(client)
    snap = client.post("/api/v1/lifecycle/forecast/refresh", headers=headers)
    assert snap.status_code == 200
    assert snap.json()["data"]["version"] == "rules-v1"
    playbooks = client.get("/api/v1/lifecycle/playbooks", headers=headers).json()["data"]
    assert playbooks
    accounts = client.get("/api/v1/accounts", headers=headers).json()["data"]
    ran = client.post(
        f"/api/v1/lifecycle/playbooks/{playbooks[0]['id']}/run",
        headers=headers,
        json={"entity_type": "account", "entity_id": accounts[0]["id"]},
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["data"]["status"] == "completed"
    runs = client.get("/api/v1/lifecycle/playbooks/runs", headers=headers)
    assert runs.status_code == 200
    assert runs.json()["meta"]["total"] >= 1


def test_health_is_rules_and_close_won_mints_onboarding(client: TestClient) -> None:
    headers = login(client)
    success = client.get("/api/v1/lifecycle/success", headers=headers)
    assert success.status_code == 200
    rows = success.json()["data"]
    assert rows
    assert rows[0]["health"]["version"] == "rules-v1"
    cards = client.get("/api/v1/lifecycle/models", headers=headers).json()["data"]
    assert all(row["version"] == "rules-v1" for row in cards)
    overview = client.get("/api/v1/command-center/overview", headers=headers)
    assert overview.status_code == 200
    life = overview.json()["data"]["lifecycle"]
    assert life["customers"] >= 1
    assert "SQL counts" in life["note"]


def test_readonly_cannot_create_campaign(client: TestClient) -> None:
    headers = login(client, "readonly@agrayian.demo")
    denied = client.post("/api/v1/lifecycle/campaigns", headers=headers, json={"name": "Nope"})
    assert denied.status_code == 403
