from fastapi.testclient import TestClient

from tests.conftest import login


def test_markets_are_tenant_scoped(client: TestClient) -> None:
    agrayian = login(client, "admin@agrayian.demo")
    northline = login(client, "admin@northline.demo")
    created = client.post(
        "/api/v1/market",
        headers=agrayian,
        json={"name": "Secret Market", "industry": "bfsi", "geography": "india"},
    )
    assert created.status_code == 200, created.text
    market_id = created.json()["data"]["id"]
    leaked = client.get(f"/api/v1/market/{market_id}", headers=northline)
    assert leaked.status_code == 404
    north_list = client.get("/api/v1/market", headers=northline).json()["data"]
    assert all(row["name"] != "Secret Market" for row in north_list)


def test_market_scores_are_deterministic(client: TestClient) -> None:
    headers = login(client)
    created = client.post(
        "/api/v1/market",
        headers=headers,
        json={"name": "Score Lab", "industry": "bfsi", "geography": "india"},
    )
    assert created.status_code == 200
    first = created.json()["data"]
    market_id = first["id"]
    second = client.post(f"/api/v1/market/{market_id}/score", headers=headers).json()["data"]
    assert first["attractiveness"] == second["attractiveness"]
    assert first["score_version"] == "rules-v1"
    assert "rules-v1" in first["score_reasons"]


def test_seeded_market_overview_is_live(client: TestClient) -> None:
    headers = login(client)
    overview = client.get("/api/v1/market/overview", headers=headers)
    assert overview.status_code == 200
    body = overview.json()["data"]
    assert body["markets"] >= 1
    assert body["signals"] >= 1
    signals = client.get("/api/v1/market/desk/signals", headers=headers)
    assert signals.status_code == 200
    assert signals.json()["meta"]["total"] >= 1


def test_inbound_capture_and_opt_out(client: TestClient) -> None:
    headers = login(client)
    accepted = client.post(
        "/api/v1/acquisition/capture",
        headers=headers,
        json={
            "first_name": "Nalini",
            "last_name": "Bose",
            "email": "nalini.bose@harborretail.example",
            "company_name": "Harbor Retail Group",
            "title": "VP Digital",
            "consent_email": True,
            "utm_source": "webinar",
            "channel": "event",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["lead"]["email"] == "nalini.bose@harborretail.example"

    duplicate = client.post(
        "/api/v1/acquisition/capture",
        headers=headers,
        json={
            "first_name": "Nalini",
            "last_name": "Bose",
            "email": "nalini.bose@harborretail.example",
            "company_name": "Harbor Retail Group",
            "consent_email": True,
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["capture"]["status"] == "duplicate_review"
    assert duplicate.json()["data"]["reviews_opened"] >= 1

    opted = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"first_name": "No", "last_name": "Mail", "email": "no.mail@example.com", "opt_out": True},
    )
    assert opted.status_code == 200
    blocked = client.post(
        "/api/v1/acquisition/capture",
        headers=headers,
        json={"first_name": "No", "last_name": "Mail", "email": "no.mail@example.com", "consent_email": True},
    )
    assert blocked.status_code == 409


def test_readonly_cannot_capture(client: TestClient) -> None:
    headers = login(client, "readonly@agrayian.demo")
    denied = client.post(
        "/api/v1/acquisition/capture",
        headers=headers,
        json={"first_name": "A", "last_name": "B", "email": "a.b@example.com"},
    )
    assert denied.status_code == 403
