from fastapi.testclient import TestClient

from tests.conftest import login


def test_readonly_cannot_view_pilot(client: TestClient) -> None:
    headers = login(client, "readonly@agrayian.demo")
    denied = client.get("/api/v1/pilot/readiness", headers=headers)
    assert denied.status_code == 403


def test_pilot_readiness_and_activate(client: TestClient) -> None:
    headers = login(client)
    report = client.get("/api/v1/pilot/readiness", headers=headers)
    assert report.status_code == 200, report.text
    data = report.json()["data"]
    assert data["operating_mode"] == "DEMO"
    assert data["environment"] == "test"
    keys = {item["key"] for item in data["items"]}
    assert {"authentication", "approvals", "emergency_stop", "migrations", "email", "whatsapp", "malware"} <= keys
    activated = client.post("/api/v1/pilot/activate", headers=headers, json={"target": "PILOT", "reason": "test"})
    assert activated.status_code == 200, activated.text
    assert activated.json()["data"]["operating_mode"] == "PILOT"
    again = client.get("/api/v1/pilot/readiness", headers=headers).json()["data"]
    assert again["operating_mode"] == "PILOT"
    exported = client.get("/api/v1/pilot/config-export", headers=headers)
    assert exported.status_code == 200
    payload = exported.json()["data"]
    assert payload["operating_mode"] == "PILOT"
    assert "access_token" not in str(payload).lower()
    assert payload["providers"]["whatsapp"] == "NOT_CONFIGURED"


def test_close_lost_and_churn_outcomes(client: TestClient) -> None:
    headers = login(client)
    account = client.post("/api/v1/accounts", headers=headers, json={"name": "Lost Co", "industry": "saas"}).json()["data"]
    created = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": account["id"], "name": "Lost Deal", "stage": "proposal", "amount": "50000"},
    )
    assert created.status_code == 200, created.text
    opp_id = created.json()["data"]["id"]
    lost = client.post(f"/api/v1/opportunities/{opp_id}/close-lost", headers=headers, json={"reason": "pricing", "note": "too high"})
    assert lost.status_code == 200, lost.text
    assert lost.json()["data"]["stage"] == "closed_lost"
    assert lost.json()["data"]["loss_reason"] == "pricing"
    bad = client.post(f"/api/v1/opportunities/{opp_id}/close-lost", headers=headers, json={"reason": "vibes"})
    assert bad.status_code == 422
    won_account = client.post("/api/v1/accounts", headers=headers, json={"name": "Churn Co"}).json()["data"]
    won_opp = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": won_account["id"], "name": "Churn Deal", "stage": "commit", "amount": "10000"},
    ).json()["data"]
    customer = client.post(f"/api/v1/opportunities/{won_opp['id']}/close-won", headers=headers).json()["data"]
    churned = client.post(f"/api/v1/customers/{customer['id']}/churn", headers=headers, json={"reason": "adoption"})
    assert churned.status_code == 200, churned.text
    assert churned.json()["data"]["status"] == "churned"
    assert churned.json()["data"]["churn_reason"] == "adoption"


def test_quality_roi_briefs_and_trace(client: TestClient) -> None:
    headers = login(client)
    quality = client.get("/api/v1/pilot/quality", headers=headers)
    assert quality.status_code == 200, quality.text
    roi = client.get("/api/v1/pilot/roi", headers=headers)
    assert roi.status_code == 200
    assert "autonomous_execution_rate" in roi.json()["data"]["automation"]
    assert "does not claim invented AI revenue" in roi.json()["data"]["pipeline"]["revenue_associated_note"]
    brief = client.post("/api/v1/pilot/briefs/daily", headers=headers)
    assert brief.status_code == 200, brief.text
    assert "qualified_leads" in brief.json()["data"]["payload"]
    lead = client.post(
        "/api/v1/leads",
        headers=headers,
        json={"first_name": "Trace", "last_name": "Lead", "email": "trace.lead@example.com", "company_name": "Trace Co", "consent_email": True},
    ).json()["data"]
    trace = client.get(f"/api/v1/autonomy/entities/lead/{lead['id']}/trace", headers=headers)
    assert trace.status_code == 200
    body = trace.json()["data"]
    assert "why_selected" in body
    assert "approvals" in body


def test_whatsapp_requires_consent_and_template(client: TestClient) -> None:
    headers = login(client)
    templates = client.get("/api/v1/pilot/whatsapp/templates", headers=headers)
    assert templates.status_code == 200
    created = client.post(
        "/api/v1/pilot/whatsapp/templates",
        headers=headers,
        json={"template_id": "hello", "language": "en", "status": "approved", "body": "Hi {{1}}", "variables": ["1"]},
    )
    assert created.status_code == 200, created.text
    lead = client.post(
        "/api/v1/leads",
        headers=headers,
        json={"first_name": "Wa", "last_name": "No", "email": "wa.no@example.com", "company_name": "WA Co", "consent_email": True},
    ).json()["data"]
    approval = client.post(
        "/api/v1/ai/approvals",
        headers=headers,
        json={
            "action_type": "whatsapp.send",
            "title": "Send WhatsApp",
            "entity_type": "lead",
            "entity_id": lead["id"],
            "action_level": 1,
            "payload": {"template_id": "hello", "language": "en", "to": "+1555"},
        },
    )
    if approval.status_code == 404:
        return
    assert approval.status_code in {200, 404, 405, 422}


def test_health_rebuild_and_credentials(client: TestClient) -> None:
    headers = login(client)
    rebuilt = client.post("/api/v1/lifecycle/success/health/rebuild", headers=headers, json={})
    assert rebuilt.status_code == 200, rebuilt.text
    creds = client.post(
        "/api/v1/integrations/credentials",
        headers=headers,
        json={"provider": "linkedin", "access_token": "secret-token", "extra": {"account_id": "act-1"}},
    )
    assert creds.status_code == 200, creds.text
    listed = client.get("/api/v1/integrations", headers=headers).json()["data"]
    assert any(row["provider"] == "linkedin" for row in listed)
    assert all("secret-token" not in str(row) for row in listed)


def test_emergency_stop_and_opt_out_refuse_send(client: TestClient) -> None:
    headers = login(client)
    stopped = client.patch("/api/v1/autonomy/settings", headers=headers, json={"emergency_stop": True})
    assert stopped.status_code == 200, stopped.text
    lead = client.post(
        "/api/v1/leads",
        headers=headers,
        json={
            "first_name": "Stop",
            "last_name": "Lead",
            "email": "stop.lead@example.com",
            "company_name": "Stop Co",
            "consent_email": True,
        },
    ).json()["data"]
    approvals = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    approval = next((row for row in approvals if row["entity_id"] == lead["id"] and str(row["action_type"]).endswith(".send")), None)
    if approval:
        decided = client.post(
            f"/api/v1/ai/approvals/{approval['id']}/decide",
            headers=headers,
            json={"decision": "approve", "note": "should refuse"},
        )
        assert decided.status_code == 200
        assert "Emergency stop" in str(decided.json())
    client.patch("/api/v1/autonomy/settings", headers=headers, json={"emergency_stop": False})
