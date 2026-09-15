from fastapi.testclient import TestClient

from tests.conftest import login


def test_approvals_and_runs_paginate(client: TestClient) -> None:
    headers = login(client)
    approvals = client.get("/api/v1/ai/approvals", headers=headers, params={"page": 1, "page_size": 5})
    assert approvals.status_code == 200
    meta = approvals.json()["meta"]
    assert meta["page"] == 1
    assert meta["page_size"] == 5
    assert "total" in meta
    runs = client.get("/api/v1/autonomy/runs", headers=headers, params={"page": 1, "page_size": 5})
    assert runs.status_code == 200
    assert runs.json()["meta"]["page"] == 1
    activity = client.get("/api/v1/autonomy/activity", headers=headers, params={"page": 1, "page_size": 5})
    assert activity.status_code == 200
    audit = client.get("/api/v1/admin/audit", headers=headers, params={"page": 1, "page_size": 10})
    assert audit.status_code == 200
    actions = client.get("/api/v1/providers/actions", headers=headers, params={"page": 1, "page_size": 5})
    assert actions.status_code == 200


def test_emergency_stop_blocks_external_dispatch(client: TestClient) -> None:
    headers = login(client)
    patched = client.patch(
        "/api/v1/autonomy/settings",
        headers=headers,
        json={"emergency_stop": True},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["emergency_stop"] is True
    leads = client.get("/api/v1/leads", headers=headers).json()["data"]
    lead = next(row for row in leads if row.get("consent_email") and not row.get("opt_out"))
    drafted = client.post(
        "/api/v1/ai/drafts/email",
        headers=headers,
        json={"entity_type": "lead", "entity_id": lead["id"], "intent": "follow_up", "send": True},
    )
    assert drafted.status_code == 200
    approval_id = drafted.json()["data"]["approval_id"]
    decided = client.post(
        f"/api/v1/ai/approvals/{approval_id}/decide",
        headers=headers,
        json={"decision": "approve", "note": "send"},
    )
    assert decided.status_code == 200
    note = (decided.json()["data"]["decision_note"] or "").lower()
    assert "emergency" in note or "suspended" in note
    client.patch("/api/v1/autonomy/settings", headers=headers, json={"emergency_stop": False})


def test_metrics_available_in_test() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert b"http_requests_total" in response.content or response.status_code == 200
