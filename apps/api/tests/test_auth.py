from fastapi.testclient import TestClient

from tests.conftest import login


def test_login_and_me(client: TestClient) -> None:
    headers = login(client)
    me = client.get("api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    body = me.json()["data"]["user"]
    assert body["email"] == "admin@agrayian.demo"
    assert "accounts.read" in body["permissions"]


def test_login_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "admin@agrayian.demo", "password": "wrong-pass"}
    )
    assert response.status_code == 401


def test_readonly_cannot_write_account(client: TestClient) -> None:
    headers = login(client, "readonly@agrayian.demo")
    response = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"name": "Should Fail"},
    )
    assert response.status_code == 403
