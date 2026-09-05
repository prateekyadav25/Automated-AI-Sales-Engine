from fastapi.testclient import TestClient

from tests.conftest import login


def test_lead_score_is_deterministic(client: TestClient) -> None:
    headers = login(client)
    leads = client.get("/api/v1/leads", headers=headers).json()["data"]
    assert leads
    lead_id = leads[0]["id"]
    first = client.post(f"/api/v1/leads/{lead_id}/score", headers=headers)
    second = client.post(f"/api/v1/leads/{lead_id}/score", headers=headers)
    assert first.status_code == 200
    assert first.json()["data"]["total"] == second.json()["data"]["total"]
    assert first.json()["data"]["version"] == "rules-v1"
    assert first.json()["data"]["reasons"]
