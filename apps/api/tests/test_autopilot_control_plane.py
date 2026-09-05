from fastapi.testclient import TestClient

from tests.conftest import login


def _enable(client: TestClient, headers: dict) -> None:
    client.patch("/api/v1/autonomy/settings", headers=headers, json={"enabled": True})


def _account_id(client: TestClient, headers: dict) -> str:
    accounts = client.get("/api/v1/accounts", headers=headers).json()["data"]
    return next(row["id"] for row in accounts if row["name"] == "Meridian Bank")


def _create_lead(client: TestClient, headers: dict, **overrides: object) -> dict:
    payload = {
        "first_name": "Ava",
        "last_name": "Control",
        "email": "ava.control@meridianbank.example",
        "company_name": "Meridian Bank",
        "title": "CIO",
        "account_id": _account_id(client, headers),
        "consent_email": True,
        "intent_score": 80,
        "engagement_score": 70,
        "has_buying_trigger": True,
    }
    payload.update(overrides)
    response = client.post("/api/v1/leads", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_consented_lead_intake_queues_approval_once(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    lead = _create_lead(client, headers)
    scored = client.get(f"/api/v1/leads/{lead['id']}", headers=headers).json()["data"]
    assert scored["latest_score"]["total"] >= 60
    trace = client.get(f"/api/v1/autonomy/entities/lead/{lead['id']}", headers=headers).json()["data"]
    assert trace["state"] in {"OUTREACH_APPROVAL_PENDING", "CONTACTED"}
    approvals = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    mine = [row for row in approvals if row.get("entity_id") == lead["id"] and row["action_type"].endswith(".send")]
    assert mine
    assert mine[0]["why"]
    client.post(f"/api/v1/leads/{lead['id']}/score", headers=headers)
    again = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    mine_again = [row for row in again if row.get("entity_id") == lead["id"] and row["action_type"].endswith(".send")]
    assert len(mine_again) == len(mine)


def test_approval_executes_mock_email(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    lead = _create_lead(client, headers, email="ava.send@meridianbank.example", first_name="Send")
    approvals = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    approval = next(row for row in approvals if row.get("entity_id") == lead["id"] and row["action_type"].endswith(".send"))
    decided = client.post(
        f"/api/v1/ai/approvals/{approval['id']}/decide",
        headers=headers,
        json={"decision": "approve", "note": "Ship it"},
    )
    assert decided.status_code == 200, decided.text
    note = decided.json()["data"]["decision_note"]
    assert "mock-email" in note or "Provider" in note
    trace = client.get(f"/api/v1/autonomy/entities/lead/{lead['id']}", headers=headers).json()["data"]
    assert trace["state"] == "CONTACTED"


def test_no_consent_does_not_queue_send(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    lead = _create_lead(
        client,
        headers,
        email="silent.autopilot@example.com",
        first_name="Silent",
        last_name="Autopilot",
        consent_email=False,
    )
    approvals = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    assert all(row.get("entity_id") != lead["id"] or not row["action_type"].endswith(".send") for row in approvals)
    trace = client.get(f"/api/v1/autonomy/entities/lead/{lead['id']}", headers=headers).json()["data"]
    assert trace["state"] == "BLOCKED"
    assert "consent" in trace["blocked_reason"].lower()


def test_disabled_autopilot_skips_intake_and_cycle(client: TestClient) -> None:
    headers = login(client)
    try:
        patched = client.patch("/api/v1/autonomy/settings", headers=headers, json={"enabled": False})
        assert patched.status_code == 200
        assert patched.json()["data"]["enabled"] is False
        lead = _create_lead(client, headers, email="off.cycle@meridianbank.example", first_name="Off")
        trace = client.get(f"/api/v1/autonomy/entities/lead/{lead['id']}", headers=headers).json()["data"]
        assert trace["state"] == "NONE"
        started = client.post("/api/v1/autonomy/runs", headers=headers, json={})
        assert started.status_code == 200
        assert started.json()["data"]["status"] == "skipped"
    finally:
        _enable(client, headers)


def test_entity_pause_stops_automation(client: TestClient) -> None:
    headers = login(client)
    _enable(client, headers)
    lead = _create_lead(client, headers, email="paused.lead@meridianbank.example", first_name="Paused")
    paused = client.post(
        "/api/v1/autonomy/pause",
        headers=headers,
        json={"scope": "lead", "entity_id": lead["id"]},
    )
    assert paused.status_code == 200
    assert paused.json()["data"]["paused"] is True
    status = client.get("/api/v1/autonomy/status", headers=headers)
    assert status.status_code == 200
    assert "today" in status.json()["data"]
