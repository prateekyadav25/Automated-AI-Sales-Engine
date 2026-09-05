from fastapi.testclient import TestClient

from tests.conftest import login


def test_close_won_creates_customer_and_renewal_stub(client: TestClient) -> None:
    headers = login(client)
    accounts = client.get("/api/v1/accounts", headers=headers).json()["data"]
    created = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={
            "account_id": accounts[0]["id"],
            "name": "Close Won Path",
            "stage": "commit",
            "amount": "100000",
            "probability": 90,
        },
    )
    assert created.status_code == 200
    opp_id = created.json()["data"]["id"]
    won = client.post(f"/api/v1/opportunities/{opp_id}/close-won", headers=headers)
    assert won.status_code == 200
    customers = client.get("/api/v1/customers", headers=headers).json()["data"]
    assert any(row["opportunity_id"] == opp_id for row in customers)
    tasks = client.get("/api/v1/tasks", headers=headers).json()["data"]
    assert any("handoff" in row["title"].lower() for row in tasks)
