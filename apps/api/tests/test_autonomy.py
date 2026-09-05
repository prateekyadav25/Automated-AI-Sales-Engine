from fastapi.testclient import TestClient

from tests.conftest import login


def test_autonomous_run_persists_and_queues_only_consented_sends(client: TestClient) -> None:
    headers = login(client)
    no_consent = client.post(
        "/api/v1/leads",
        headers=headers,
        json={
            "first_name": "Silent",
            "last_name": "Buyer",
            "email": "silent.buyer@example.com",
            "company_name": "Quiet Co",
            "consent_email": False,
        },
    )
    assert no_consent.status_code == 200
    started = client.post("/api/v1/autonomy/runs", headers=headers, json={})
    assert started.status_code == 200, started.text
    run = started.json()["data"]
    assert run["status"] == "completed"
    names = [step["name"] for step in run["steps"]]
    assert names == ["discover", "refresh_markets", "rescore", "propose_enrollments", "queue_approvals"]
    approvals = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    titles = [row["title"] for row in approvals]
    assert all("silent.buyer@example.com" not in title for title in titles)
    listed = client.get("/api/v1/autonomy/runs", headers=headers)
    assert listed.status_code == 200
    assert any(row["id"] == run["id"] for row in listed.json()["data"])


def test_autonomous_run_is_tenant_scoped(client: TestClient) -> None:
    agrayian = login(client, "admin@agrayian.demo")
    northline = login(client, "admin@northline.demo")
    created = client.post("/api/v1/autonomy/runs", headers=agrayian, json={})
    assert created.status_code == 200
    run_id = created.json()["data"]["id"]
    leaked = client.get(f"/api/v1/autonomy/runs/{run_id}", headers=northline)
    assert leaked.status_code == 404
    other = client.get("/api/v1/autonomy/runs", headers=northline).json()["data"]
    assert all(row["id"] != run_id for row in other)


def test_readonly_cannot_start_run(client: TestClient) -> None:
    headers = login(client, "readonly@agrayian.demo")
    denied = client.post("/api/v1/autonomy/runs", headers=headers, json={})
    assert denied.status_code == 403
