from decimal import Decimal

from fastapi.testclient import TestClient

from tests.conftest import login


def test_launch_queues_approval_and_mock_does_not_invent_spend(client: TestClient) -> None:
    headers = login(client)
    created = client.post(
        "/api/v1/lifecycle/campaigns",
        headers=headers,
        json={"name": "LinkedIn hunt", "channel": "linkedin", "objective": "pipeline", "budget": "2500"},
    )
    assert created.status_code == 200
    campaign_id = created.json()["data"]["id"]
    assert created.json()["data"]["spent"] in {"0", "0.00", 0}
    launch = client.post(f"/api/v1/lifecycle/campaigns/{campaign_id}/launch", headers=headers)
    assert launch.status_code == 200, launch.text
    approval_id = launch.json()["data"]["approval_id"]
    decided = client.post(
        f"/api/v1/ai/approvals/{approval_id}/decide",
        headers=headers,
        json={"decision": "approve", "note": "Try launch"},
    )
    assert decided.status_code == 200
    note = decided.json()["data"]["decision_note"]
    assert "invented" in note.lower() or "not launched" in note.lower() or "no live" in note.lower()
    detail = client.get(f"/api/v1/lifecycle/campaigns/{campaign_id}", headers=headers).json()["data"]
    assert detail["status"] != "launched"
    assert Decimal(str(detail["spent"])) == Decimal("0")


def test_outbound_campaign_cannot_launch(client: TestClient) -> None:
    headers = login(client)
    created = client.post(
        "/api/v1/lifecycle/campaigns",
        headers=headers,
        json={"name": "Outbound only", "channel": "outbound", "budget": "100"},
    )
    campaign_id = created.json()["data"]["id"]
    launch = client.post(f"/api/v1/lifecycle/campaigns/{campaign_id}/launch", headers=headers)
    assert launch.status_code == 409
