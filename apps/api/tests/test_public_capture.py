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
    assert lead["ad_id"] == "ad-22"
    auth = client.get("/api/v1/acquisition/form-keys", headers=headers)
    assert auth.status_code == 200
    assert any(row["name"] == "site" for row in auth.json()["data"])
