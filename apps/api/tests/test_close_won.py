"""The operator close-won path needs an accepted quote. The historical activation stays on close_won()."""

from uuid import UUID

from fastapi.testclient import TestClient

from app.db.session import get_session
from app.services.crm import close_won
from tests.conftest import login


def test_http_close_won_without_a_quote_is_refused(client: TestClient) -> None:
    headers = login(client)
    accounts = client.get("/api/v1/accounts", headers=headers).json()["data"]
    created = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": accounts[0]["id"], "name": "Unquoted close", "stage": "commit", "amount": "100000"},
    )
    assert created.status_code == 200, created.text
    opp_id = created.json()["data"]["id"]
    refused = client.post(f"/api/v1/opportunities/{opp_id}/close-won", headers=headers, json={})
    assert refused.status_code == 422
    customers = client.get("/api/v1/customers", headers=headers).json()["data"]
    assert all(row["opportunity_id"] != opp_id for row in customers)


def test_historical_close_won_still_creates_the_renewal_stub(client: TestClient) -> None:
    headers = login(client)
    accounts = client.get("/api/v1/accounts", headers=headers).json()["data"]
    created = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": accounts[0]["id"], "name": "Historical activation", "stage": "commit", "amount": "100000"},
    )
    opp_id = created.json()["data"]["id"]
    user = client.get("/api/v1/auth/me", headers=headers).json()["data"]["user"]
    db = get_session()
    try:
        _opp, customer, renewal = close_won(
            db,
            tenant_id=UUID(user["tenant_id"]),
            actor_id=UUID(user["id"]),
            opportunity_id=UUID(opp_id),
            historical_fixture=True,
        )
        db.commit()
        assert customer.opportunity_id == UUID(opp_id)
        assert renewal.customer_id == customer.id
    finally:
        db.close()


def test_close_won_without_the_historical_boundary_does_not_activate(client: TestClient) -> None:
    headers = login(client)
    accounts = client.get("/api/v1/accounts", headers=headers).json()["data"]
    created = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": accounts[0]["id"], "name": "Unguarded activation", "stage": "commit", "amount": "100000"},
    )
    opp_id = created.json()["data"]["id"]
    user = client.get("/api/v1/auth/me", headers=headers).json()["data"]["user"]
    before = client.get("/api/v1/customers", headers=headers).json()["data"]
    db = get_session()
    try:
        try:
            close_won(
                db,
                tenant_id=UUID(user["tenant_id"]),
                actor_id=UUID(user["id"]),
                opportunity_id=UUID(opp_id),
            )
        except ValueError as exc:
            assert "accepted-quote" in str(exc)
        else:
            raise AssertionError("close_won created a customer without the historical boundary")
        db.rollback()
    finally:
        db.close()
    after = client.get("/api/v1/customers", headers=headers).json()["data"]
    assert len(after) == len(before)
    opportunity = client.get(f"/api/v1/opportunities/{opp_id}", headers=headers).json()["data"]
    assert opportunity["stage"] != "closed_won"
