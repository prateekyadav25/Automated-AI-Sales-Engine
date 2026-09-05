from fastapi.testclient import TestClient

from tests.conftest import login


def test_copilot_uses_mock_when_unconfigured(client: TestClient) -> None:
    headers = login(client)
    accounts = client.get("/api/v1/accounts", headers=headers).json()["data"]
    response = client.post(
        "/api/v1/ai/copilot/chat",
        headers=headers,
        json={"message": f"Research account {accounts[0]['name']}"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["is_mock"] is True
    assert body["reply"]


def test_email_send_queues_approval(client: TestClient) -> None:
    headers = login(client)
    leads = client.get("/api/v1/leads", headers=headers).json()["data"]
    lead = next(row for row in leads if row.get("consent_email") and not row.get("opt_out"))
    response = client.post(
        "/api/v1/ai/drafts/email",
        headers=headers,
        json={"entity_type": "lead", "entity_id": lead["id"], "intent": "follow_up", "send": True},
    )
    assert response.status_code == 200
    assert response.json()["data"]["approval_id"] is not None
    approvals = client.get("/api/v1/ai/approvals", headers=headers).json()["data"]
    assert approvals


def test_knowledge_is_tenant_scoped(client: TestClient) -> None:
    agrayian = login(client, "admin@agrayian.demo")
    northline = login(client, "admin@northline.demo")
    hits_a = client.get("/api/v1/ai/knowledge/search", headers=agrayian, params={"q": "governance"}).json()[
        "data"
    ]
    hits_b = client.get("/api/v1/ai/knowledge/search", headers=northline, params={"q": "governance"}).json()[
        "data"
    ]
    assert hits_a
    assert hits_b == []
