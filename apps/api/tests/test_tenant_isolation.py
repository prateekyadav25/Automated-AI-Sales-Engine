from fastapi.testclient import TestClient

from tests.conftest import login


def test_cannot_read_other_tenant_account(client: TestClient) -> None:
    agrayian = login(client, "admin@agrayian.demo")
    northline = login(client, "admin@northline.demo")
    created = client.post("/api/v1/accounts", headers=agrayian, json={"name": "Secret Tenant A"})
    assert created.status_code == 200
    account_id = created.json()["data"]["id"]
    leaked = client.get(f"/api/v1/accounts/{account_id}", headers=northline)
    assert leaked.status_code == 404


def test_kpis_are_tenant_scoped(client: TestClient) -> None:
    agrayian = login(client, "admin@agrayian.demo")
    northline = login(client, "admin@northline.demo")
    a = client.get("/api/v1/command-center/kpis", headers=agrayian).json()["data"]
    b = client.get("/api/v1/command-center/kpis", headers=northline).json()["data"]
    assert a["total_accounts"] != b["total_accounts"] or a["total_leads"] != b["total_leads"]
