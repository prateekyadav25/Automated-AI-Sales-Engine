from fastapi.testclient import TestClient

from tests.conftest import login


def test_refresh_rotates_and_reuse_revokes_family(client: TestClient) -> None:
    login_res = client.post("/api/v1/auth/login", json={"email": "admin@agrayian.demo", "password": "Agrarian!Demo1"})
    assert login_res.status_code == 200
    first = login_res.cookies.get("refresh_token")
    assert first
    rotated = client.post("/api/v1/auth/refresh", cookies={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.cookies.get("refresh_token")
    assert second
    reused = client.post("/api/v1/auth/refresh", cookies={"refresh_token": first})
    assert reused.status_code == 401
    after = client.post("/api/v1/auth/refresh", cookies={"refresh_token": second})
    assert after.status_code == 401


def test_sessions_list_and_revoke(client: TestClient) -> None:
    headers = login(client)
    listed = client.get("/api/v1/auth/sessions", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()["data"]
    assert rows
    family_id = rows[0]["family_id"]
    revoked = client.post(f"/api/v1/auth/sessions/{family_id}/revoke", headers=headers)
    assert revoked.status_code == 200


def test_failed_login_is_generic(client: TestClient) -> None:
    missing = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "Agrarian!Demo1"})
    wrong = client.post("/api/v1/auth/login", json={"email": "admin@agrayian.demo", "password": "wrong-pass-99"})
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["detail"] == wrong.json()["detail"] == "Invalid credentials"
