from fastapi.testclient import TestClient

from tests.conftest import login


def test_contact_list_includes_account_name(client: TestClient) -> None:
    headers = login(client)
    response = client.get("/api/v1/contacts", headers=headers)
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows
    attached = [row for row in rows if row.get("account_id")]
    assert attached
    for row in attached:
        assert row["account_name"]
    named = next(row for row in attached if row["first_name"] == "Anita")
    detail = client.get(f"/api/v1/contacts/{named['id']}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()["data"]
    assert body["account_name"] == named["account_name"]
    assert body["account_id"] == named["account_id"]


def test_unattached_contact_has_null_account_name(client: TestClient) -> None:
    headers = login(client)
    created = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"first_name": "Offline", "last_name": "Lead", "email": "offline.lead@example.com"},
    )
    assert created.status_code == 200
    payload = created.json()["data"]
    assert payload["account_id"] is None
    assert payload["account_name"] is None
