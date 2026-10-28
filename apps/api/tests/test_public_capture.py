from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session
from app.models.identity import User
from app.services.public_forms import create_form_key
from tests.conftest import login


def test_public_form_capture_is_key_scoped(client: TestClient) -> None:
    headers = login(client)
    db = get_session()
    try:
        user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
        _row, token = create_form_key(db, tenant_id=user.tenant_id, actor_id=user.id, name="site")
        db.commit()
    finally:
        db.close()
    denied = client.post("/api/v1/public/forms/not-a-real-token/capture", json={"first_name": "A", "last_name": "B", "email": "a@example.com", "consent_email": True})
    assert denied.status_code == 401
    accepted = client.post(
        f"/api/v1/public/forms/{token}/capture",
        json={
            "first_name": "Priya",
            "last_name": "Shah",
            "email": "priya.public@example.com",
            "company_name": "Public Co",
            "consent_email": True,
            "phone": "9990001111",
            "request_note": "We want a governed operations workflow for dispatch.",
            "utm_source": "linkedin",
            "utm_medium": "paid",
            "utm_campaign": "q3",
            "ad_id": "ad-22",
        },
    )
    assert accepted.status_code == 200, accepted.text
    lead = accepted.json()["data"]["lead"]
    assert lead["email"] == "priya.public@example.com"
    assert lead["utm_medium"] == "paid"
    assert lead["ad_id"] == ""
    assert "dispatch" in lead["notes"]
    auth = client.get("/api/v1/acquisition/form-keys", headers=headers)
    assert auth.status_code == 200
    listed = next(row for row in auth.json()["data"] if row["name"] == "site")
    assert listed["url"].endswith(f"/capture/{token}")
    page = client.get(f"/api/v1/public/forms/{token}")
    assert page.status_code == 200
    assert "site" in page.text
    meta = client.get(f"/api/v1/public/forms/{token}/meta")
    assert meta.status_code == 200
    assert meta.json()["data"]["name"] == "site"
    assert any(field["key"] == "email" for field in meta.json()["data"]["fields"])


def test_designed_form_is_what_people_fill_in(client: TestClient) -> None:
    headers = login(client)
    created = client.post(
        "/api/v1/acquisition/form-keys",
        headers=headers,
        json={
            "name": "Campus visit",
            "fields": [
                {"key": "first_name", "label": "Given name", "type": "text", "required": True, "placeholder": "", "options": []},
                {"key": "last_name", "label": "Family name", "type": "text", "required": True, "placeholder": "", "options": []},
                {"key": "email", "label": "Email", "type": "email", "required": True, "placeholder": "", "options": []},
                {"key": "request_note", "label": "Visit goal", "type": "textarea", "required": True, "placeholder": "Why visit?", "options": []},
                {"key": "consent_email", "label": "Contact me", "type": "checkbox", "required": True, "placeholder": "", "options": []},
                {"key": "custom_budget", "label": "Budget", "type": "select", "required": False, "placeholder": "", "options": ["Under 10", "Over 10"]},
            ],
        },
    )
    assert created.status_code == 200, created.text
    token = created.json()["data"]["url"].rsplit("/", 1)[-1]
    page = client.get(f"/api/v1/public/forms/{token}")
    assert page.status_code == 200
    assert "Given name" in page.text
    assert "Budget" in page.text
    assert "Phone" not in page.text


def test_incomplete_interest_stays_in_review(client: TestClient) -> None:
    db = get_session()
    try:
        user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
        _row, token = create_form_key(db, tenant_id=user.tenant_id, actor_id=user.id, name="interest-review")
        db.commit()
    finally:
        db.close()
    held = client.post(
        f"/api/v1/public/forms/{token}/capture",
        json={
            "first_name": "Asha",
            "last_name": "Rao",
            "email": "asha.review@example.com",
            "consent_email": True,
        },
    )
    assert held.status_code == 200, held.text
    data = held.json()["data"]
    assert data["lead"] is None
    assert data["capture"]["status"] == "review"
    assert data["capture"]["email"] == "asha.review@example.com"
