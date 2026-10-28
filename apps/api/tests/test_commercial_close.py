"""Accepted quote, authorized close-won, frozen purchase, and one onboarding task."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.session import get_session
from app.models.ai import AIApproval
from app.models.crm import Task
from app.models.execution import JourneyLink
from app.models.integrations import EmailMessage
from app.models.lifecycle import DealPurchase, OnboardingPlan, Product, Quote
from app.models.operating_plan import DemoScope
from app.models.post_sale import Contract
from app.services.commercial_close import decide_close_won
from app.services.demo_guard import EXPIRED_BLOCK, PREPARED_BLOCK
from app.services.dispatcher import dispatch_approval
from tests.conftest import login

PRICE = "125000.50"
TOTAL = Decimal("250001.00")


def _user(client: TestClient, headers: dict) -> dict:
    return client.get("/api/v1/auth/me", headers=headers).json()["data"]["user"]


def _ready(
    client: TestClient,
    headers: dict,
    *,
    name: str,
    currency: str = "USD",
    valid: str | None = None,
    relationship: str = "economic_buyer",
    source: str = "manual",
    cadence: str = "annual",
    quantity: int = 2,
    service_start: str | None = "2026-11-01",
    service_end: str | None = "2027-11-01",
    accept_contact: dict | None = None,
) -> dict:
    stamp = uuid4().hex[:8]
    account = client.post("/api/v1/accounts", headers=headers, json={"name": f"{name} {stamp}"}).json()["data"]
    contact = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"account_id": account["id"], "first_name": "Buyer", "last_name": stamp, "email": f"{stamp}@example.com", "buying_role": relationship},
    ).json()["data"]
    product = client.post(
        "/api/v1/lifecycle/products",
        headers=headers,
        json={"sku": f"NDR{stamp[:4]}", "name": f"Northline Desk {stamp}", "kind": "one_time", "list_price": PRICE, "currency": currency},
    ).json()["data"]
    opportunity = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": account["id"], "name": f"{name} deal", "stage": "commit", "amount": "10.00", "probability": 80},
    ).json()["data"]
    created = client.post(
        "/api/v1/lifecycle/quotes",
        headers=headers,
        json={
            "opportunity_id": opportunity["id"],
            "discount_pct": 0,
            "tax_pct": 0,
            "scope_text": "One desk router",
            "terms": "Net 30",
            "billing_cadence": cadence,
            "service_start": service_start,
            "service_end": service_end,
            "valid_until": valid or (datetime.now(UTC) + timedelta(days=14)).isoformat(),
            "offer_label": "Desk",
            "lines": [{"product_id": product["id"], "quantity": quantity, "unit_price": PRICE}],
        },
    )
    assert created.status_code == 200, created.text
    quote = created.json()["data"]
    issued = client.post(f"/api/v1/lifecycle/quotes/{quote['id']}/issue", headers=headers)
    assert issued.status_code == 200, issued.text
    accepted = client.post(
        f"/api/v1/workflow/quotes/{quote['id']}/accept",
        headers=headers,
        json={
            "contact_id": (accept_contact or contact)["id"],
            "relationship": relationship,
            "source": source,
            "evidence": "Fixture acceptance note",
        },
    )
    assert accepted.status_code == 200, accepted.text
    return {
        "account": account,
        "contact": contact,
        "product": product,
        "opportunity": opportunity,
        "quote": issued.json()["data"],
        "acceptance": accepted.json()["data"],
    }


def _customers(client: TestClient, headers: dict, account_id: str) -> list[dict]:
    rows = client.get("/api/v1/customers", headers=headers).json()["data"]
    return [row for row in rows if row["account_id"] == account_id]


def _close(client: TestClient, headers: dict, row: dict) -> dict:
    response = client.post(
        f"/api/v1/opportunities/{row['opportunity']['id']}/close-won",
        headers=headers,
        json={"quote_id": row["quote"]["id"], "note": "Operator decision"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_acceptance_does_not_create_a_customer_and_close_won_is_explicit(client: TestClient) -> None:
    headers = login(client)
    row = _ready(client, headers, name="Close path")
    assert row["acceptance"]["customer_created"] is False
    assert row["acceptance"]["review_state"] == "recorded"
    assert _customers(client, headers, row["account"]["id"]) == []
    before_mail = _count(EmailMessage)
    view = _close(client, headers, row)
    assert view["won"] is True
    assert view["provider_verified"] is False
    assert view["activated"] is False
    assert view["payment_status"] == ""
    assert view["external_released"] is False
    assert view["currency"] == "USD"
    assert Decimal(str(view["total"])) == TOTAL
    assert view["discount_pct"] is None
    assert view["tax_pct"] is None
    assert view["customer_facing_name"].startswith("Northline Desk")
    assert view["sku"].startswith("NDR")
    assert view["offer_label"] == "Desk"
    assert view["scope_text"] == "One desk router"
    assert view["onboarding_status"] == "open"
    assert view["task_status"] == "open"
    assert view["owner_name"]
    assert "Payment is not recorded" in view["note"] or "does not send" in view["note"]
    customers = _customers(client, headers, row["account"]["id"])
    assert len(customers) == 1
    assert customers[0]["status"] == "onboarding"
    assert Decimal(str(customers[0]["arr"])) == Decimal("0")
    assert _count(EmailMessage) == before_mail
    db = get_session()
    try:
        opp_id = UUID(row["opportunity"]["id"])
        contracts = int(db.scalar(select(func.count()).select_from(Contract).where(Contract.opportunity_id == opp_id)) or 0)
        plans = int(db.scalar(select(func.count()).select_from(OnboardingPlan).where(OnboardingPlan.opportunity_id == opp_id)) or 0)
        tasks = int(db.scalar(select(func.count()).select_from(Task).where(Task.entity_id == str(opp_id), Task.deleted_at.is_(None))) or 0)
        links = int(
            db.scalar(
                select(func.count()).select_from(JourneyLink).where(JourneyLink.entity_id == str(opp_id), JourneyLink.entity_type == "opportunity")
            )
            or 0
        )
        assert contracts == 0
        assert plans == 1
        assert tasks == 1
        assert links == 1
    finally:
        db.close()
    again = _close(client, headers, row)
    assert again["customer_id"] == view["customer_id"]
    assert again["task_id"] == view["task_id"]


def test_unauthorized_missing_and_conflicting_evidence_are_refused(client: TestClient) -> None:
    headers = login(client)
    row = _ready(client, headers, name="Evidence")
    readonly = login(client, "readonly@agrayian.demo")
    denied = client.post(
        f"/api/v1/opportunities/{row['opportunity']['id']}/close-won",
        headers=readonly,
        json={"quote_id": row["quote"]["id"]},
    )
    assert denied.status_code == 403
    bare = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": row["account"]["id"], "name": "No quote", "stage": "commit", "amount": "5"},
    ).json()["data"]
    missing = client.post(f"/api/v1/opportunities/{bare['id']}/close-won", headers=headers, json={"quote_id": row["quote"]["id"]})
    assert missing.status_code == 409
    assert "does not belong" in missing.json()["detail"]
    other = client.post("/api/v1/accounts", headers=headers, json={"name": f"Other {uuid4().hex[:6]}"}).json()["data"]
    stranger = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"account_id": other["id"], "first_name": "Other", "last_name": "Buyer", "email": f"{uuid4().hex[:6]}@example.com"},
    ).json()["data"]
    wrong_person = _ready(client, headers, name="Wrong person", relationship="")
    assert wrong_person["acceptance"]["review_state"] == "incomplete"
    stranger_quote = _ready(client, headers, name="Wrong account", accept_contact=stranger)
    blocked = client.post(
        f"/api/v1/opportunities/{wrong_person['opportunity']['id']}/close-won",
        headers=headers,
        json={"quote_id": wrong_person["quote"]["id"]},
    )
    assert blocked.status_code == 409
    assert _customers(client, headers, wrong_person["account"]["id"]) == []
    stranger_close = client.post(
        f"/api/v1/opportunities/{stranger_quote['opportunity']['id']}/close-won",
        headers=headers,
        json={"quote_id": stranger_quote["quote"]["id"]},
    )
    assert stranger_close.status_code == 409
    assert "account" in stranger_close.json()["detail"].lower()
    northline = login(client, "admin@northline.demo")
    foreign = client.post(
        f"/api/v1/opportunities/{row['opportunity']['id']}/close-won",
        headers=northline,
        json={"quote_id": row["quote"]["id"]},
    )
    assert foreign.status_code == 404


def test_document_evidence_is_not_proof_and_a_provider_is_not_invented(client: TestClient) -> None:
    headers = login(client)
    row = _ready(client, headers, name="Document", source="document")
    assert row["acceptance"]["review_state"] == "needs_review"
    refused = client.post(
        f"/api/v1/opportunities/{row['opportunity']['id']}/close-won",
        headers=headers,
        json={"quote_id": row["quote"]["id"]},
    )
    assert refused.status_code == 409
    assert "review" in refused.json()["detail"].lower()
    reviewed = client.post(
        f"/api/v1/workflow/quotes/{row['quote']['id']}/acceptance/review",
        headers=headers,
        json={"note": "Operator reviewed the uploaded note"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["data"]["provider_verified"] is False
    view = _close(client, headers, row)
    assert view["acceptance_review"] == "reviewed"
    assert view["provider_verified"] is False
    issued = client.post(
        "/api/v1/lifecycle/quotes",
        headers=headers,
        json={
            "opportunity_id": row["opportunity"]["id"],
            "lines": [{"product_id": row["product"]["id"], "quantity": 1, "unit_price": "5.00"}],
        },
    )
    assert issued.status_code == 200, issued.text
    provider_quote = issued.json()["data"]["id"]
    assert client.post(f"/api/v1/lifecycle/quotes/{provider_quote}/issue", headers=headers).status_code == 200
    provider = client.post(
        f"/api/v1/workflow/quotes/{provider_quote}/accept",
        headers=headers,
        json={"source": "provider", "relationship": "buyer", "evidence": "signed"},
    )
    assert provider.status_code == 409
    assert "provider" in provider.json()["detail"].lower()


def test_product_edits_and_superseded_versions_do_not_change_the_purchase(client: TestClient) -> None:
    headers = login(client)
    row = _ready(client, headers, name="Frozen")
    db = get_session()
    try:
        product = db.get(Product, UUID(row["product"]["id"]))
        assert product is not None
        product.name = "Renamed after quote"
        product.list_price = Decimal("1.00")
        db.commit()
    finally:
        db.close()
    quoted = client.get(f"/api/v1/lifecycle/quotes/{row['quote']['id']}", headers=headers).json()["data"]
    assert quoted["customer_facing_name"].startswith("Northline Desk")
    assert Decimal(str(quoted["lines"][0]["unit_price"])) == Decimal(PRICE)
    edited = client.post(
        f"/api/v1/lifecycle/quotes/{row['quote']['id']}/lines",
        headers=headers,
        json={"product_id": row["product"]["id"], "quantity": 1, "unit_price": "9.00"},
    )
    assert edited.status_code == 200, edited.text
    successor = edited.json()["data"]
    assert successor["id"] != row["quote"]["id"]
    assert successor["status"] == "draft"
    original = client.get(f"/api/v1/lifecycle/quotes/{row['quote']['id']}", headers=headers).json()["data"]
    assert original["status"] == "accepted"
    assert Decimal(str(original["total"])) == TOTAL
    issued = client.post(f"/api/v1/lifecycle/quotes/{successor['id']}/issue", headers=headers)
    assert issued.status_code == 200, issued.text
    accepted = client.post(
        f"/api/v1/workflow/quotes/{successor['id']}/accept",
        headers=headers,
        json={"contact_id": row["contact"]["id"], "relationship": "economic_buyer", "source": "manual", "evidence": "later version"},
    )
    assert accepted.status_code == 200, accepted.text
    stale = client.post(
        f"/api/v1/opportunities/{row['opportunity']['id']}/close-won",
        headers=headers,
        json={"quote_id": row["quote"]["id"]},
    )
    assert stale.status_code == 409
    assert "superseded" in stale.json()["detail"].lower()
    won = client.post(
        f"/api/v1/opportunities/{row['opportunity']['id']}/close-won",
        headers=headers,
        json={"quote_id": successor["id"]},
    )
    assert won.status_code == 200, won.text
    body = won.json()["data"]
    assert body["customer_facing_name"].startswith("Northline Desk")
    assert "Renamed after quote" not in body["customer_facing_name"]
    db = get_session()
    try:
        first = db.get(Quote, UUID(row["quote"]["id"]))
        assert first is not None and first.status == "accepted"
        purchase = db.scalar(select(DealPurchase).where(DealPurchase.opportunity_id == UUID(row["opportunity"]["id"])))
        assert purchase is not None
        assert "125000.50" in purchase.snapshot_json
        assert purchase.payment_status == ""
        original_lines = client.get(f"/api/v1/lifecycle/quotes/{row['quote']['id']}", headers=headers).json()["data"]["lines"]
        assert all("Renamed after quote" not in line["customer_facing_name"] for line in original_lines)
    finally:
        db.close()


def test_duplicate_replay_second_purchase_and_correction(client: TestClient, monkeypatch) -> None:
    headers = login(client)
    row = _ready(client, headers, name="Replay", cadence="")
    user = _user(client, headers)
    db = get_session()
    try:
        monkeypatch.setattr("app.services.commercial_close.link_journey", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("conversion failed")))
        try:
            decide_close_won(
                db,
                tenant_id=UUID(user["tenant_id"]),
                actor_id=UUID(user["id"]),
                opportunity_id=UUID(row["opportunity"]["id"]),
                quote_id=UUID(row["quote"]["id"]),
            )
            raise AssertionError("conversion should have failed")
        except RuntimeError:
            db.rollback()
    finally:
        db.close()
    assert _customers(client, headers, row["account"]["id"]) == []
    monkeypatch.undo()
    first = _close(client, headers, row)
    assert "Billing cadence" in first["missing_information"]
    assert first["task_status"] == "open"
    second_product = client.post(
        "/api/v1/lifecycle/products",
        headers=headers,
        json={"sku": f"SEC{uuid4().hex[:4]}", "name": "Second purchase router", "kind": "one_time", "list_price": "80.00", "currency": "USD"},
    ).json()["data"]
    second_opp = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": row["account"]["id"], "name": "Second purchase", "stage": "commit", "amount": "80"},
    ).json()["data"]
    created = client.post(
        "/api/v1/lifecycle/quotes",
        headers=headers,
        json={
            "opportunity_id": second_opp["id"],
            "lines": [{"product_id": second_product["id"], "quantity": 1, "unit_price": "80.00"}],
            "scope_text": "Second scope",
            "valid_until": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
        },
    )
    assert created.status_code == 200, created.text
    quote_id = created.json()["data"]["id"]
    assert client.post(f"/api/v1/lifecycle/quotes/{quote_id}/issue", headers=headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/workflow/quotes/{quote_id}/accept",
            headers=headers,
            json={"contact_id": row["contact"]["id"], "relationship": "economic_buyer", "source": "fixture", "evidence": "second"},
        ).status_code
        == 200
    )
    second = client.post(
        f"/api/v1/opportunities/{second_opp['id']}/close-won",
        headers=headers,
        json={"quote_id": quote_id},
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["customer_id"] == first["customer_id"]
    assert second.json()["data"]["task_id"] != first["task_id"]
    assert second.json()["data"]["customer_facing_name"] == "Second purchase router"
    assert Decimal(str(second.json()["data"]["total"])) == Decimal("80.00")
    detail = client.get(f"/api/v1/post-sale/customers/{first['customer_id']}", headers=headers).json()["data"]
    names = {item["customer_facing_name"] for item in detail["purchases"]}
    assert any(name.startswith("Northline Desk") for name in names)
    assert "Second purchase router" in names
    corrected = client.post(
        f"/api/v1/opportunities/{row['opportunity']['id']}/close-won/correct",
        headers=headers,
        json={"reason": "Wrong commercial snapshot"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["data"]["purchase_status"] == "reversed"
    assert corrected.json()["data"]["stage"] == "commit"
    still = client.get(f"/api/v1/customers/{first['customer_id']}", headers=headers)
    assert still.status_code == 200
    db = get_session()
    try:
        purchase = db.scalar(select(DealPurchase).where(DealPurchase.opportunity_id == UUID(row["opportunity"]["id"])))
        plan = db.get(OnboardingPlan, UUID(first["onboarding_plan_id"]))
        assert purchase is not None and purchase.status == "reversed"
        assert plan is not None and plan.deleted_at is None
    finally:
        db.close()


def test_money_ledger_worker_and_scopes(client: TestClient) -> None:
    headers = login(client)
    mixed_account = client.post("/api/v1/accounts", headers=headers, json={"name": f"Mixed {uuid4().hex[:6]}"}).json()["data"]
    contact = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"account_id": mixed_account["id"], "first_name": "Mix", "last_name": "Buyer", "email": f"{uuid4().hex[:6]}@example.com"},
    ).json()["data"]
    usd = client.post(
        "/api/v1/lifecycle/products",
        headers=headers,
        json={"sku": f"U{uuid4().hex[:4]}", "name": "USD item", "list_price": "10", "currency": "USD"},
    ).json()["data"]
    inr = client.post(
        "/api/v1/lifecycle/products",
        headers=headers,
        json={"sku": f"I{uuid4().hex[:4]}", "name": "INR item", "list_price": "10", "currency": "INR"},
    ).json()["data"]
    opportunity = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": mixed_account["id"], "name": "Mixed currency", "stage": "commit", "amount": "20"},
    ).json()["data"]
    created = client.post(
        "/api/v1/lifecycle/quotes",
        headers=headers,
        json={"opportunity_id": opportunity["id"], "lines": [{"product_id": usd["id"], "quantity": 1, "unit_price": "10"}, {"product_id": inr["id"], "quantity": 1, "unit_price": "10"}]},
    )
    assert created.status_code == 200, created.text
    quote = created.json()["data"]
    assert quote["currency"] == ""
    assert client.post(f"/api/v1/lifecycle/quotes/{quote['id']}/issue", headers=headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/workflow/quotes/{quote['id']}/accept",
            headers=headers,
            json={"contact_id": contact["id"], "relationship": "buyer", "source": "manual", "evidence": "mixed"},
        ).status_code
        == 200
    )
    mixed = client.post(f"/api/v1/opportunities/{opportunity['id']}/close-won", headers=headers, json={"quote_id": quote["id"]})
    assert mixed.status_code == 409
    assert "currency" in mixed.json()["detail"].lower()
    expired = _ready(client, headers, name="Expired", valid="2020-01-01T00:00:00+00:00")
    old = client.post(
        f"/api/v1/opportunities/{expired['opportunity']['id']}/close-won",
        headers=headers,
        json={"quote_id": expired["quote"]["id"]},
    )
    assert old.status_code == 409
    assert "expired" in old.json()["detail"].lower()
    won = _ready(client, headers, name="Ledger")
    view = _close(client, headers, won)
    ledger = client.get("/api/v1/lifecycle/commercial-ledger", headers=headers)
    assert ledger.status_code == 200, ledger.text
    body = ledger.json()["data"]
    assert body["conversion"] is None
    assert body["invoiced"] is None
    assert body["collected"] is None
    real_usd = body["real"].get("USD", {})
    fixture_usd = body["fixture"].get("USD", {})
    assert Decimal(str(real_usd.get("closed_won", "0"))) == Decimal("0")
    assert Decimal(str(fixture_usd.get("closed_won", "0"))) >= TOTAL
    assert fixture_usd.get("invoiced") is None
    assert fixture_usd.get("collected") is None
    user = _user(client, headers)
    db = get_session()
    try:
        approval = AIApproval(
            tenant_id=UUID(user["tenant_id"]),
            created_by=UUID(user["id"]),
            action_level=2,
            action_type="commercial.close_won",
            title="Worker must not close",
            payload_json="{}",
            status="pending",
            entity_type="opportunity",
            entity_id=str(uuid4()),
        )
        db.add(approval)
        db.commit()
        db.refresh(approval)
        message = dispatch_approval(db, tenant_id=approval.tenant_id, actor_id=UUID(user["id"]), row=approval)
        assert "did not convert" in message
        approval.status = "rejected"
        db.commit()
        scope = DemoScope(
            tenant_id=UUID(user["tenant_id"]),
            created_by=UUID(user["id"]),
            status="prepared",
            expires_at=datetime(2026, 10, 29, 18, 3, tzinfo=UTC),
        )
        db.add(scope)
        db.commit()
        scope_id = scope.id
    finally:
        db.close()
    try:
        scoped = _ready(client, headers, name="Prepared scope")
        prepared = _close(client, headers, scoped)
        assert prepared["external_released"] is False
        assert prepared["external_block"] == PREPARED_BLOCK
        db = get_session()
        try:
            row = db.get(DemoScope, scope_id)
            assert row is not None
            row.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
            db.commit()
        finally:
            db.close()
        expired_scope = _ready(client, headers, name="Expired scope")
        held = _close(client, headers, expired_scope)
        assert held["external_released"] is False
        assert held["external_block"] == EXPIRED_BLOCK
    finally:
        db = get_session()
        try:
            row = db.get(DemoScope, scope_id)
            if row is not None:
                db.delete(row)
                db.commit()
        finally:
            db.close()
    patched = client.patch(
        f"/api/v1/opportunities/{won['opportunity']['id']}",
        headers=headers,
        json={"account_id": won["account"]["id"], "name": won["opportunity"]["name"], "stage": "commit", "amount": "10"},
    )
    assert patched.status_code == 409
    forced = client.patch(
        f"/api/v1/opportunities/{expired['opportunity']['id']}",
        headers=headers,
        json={"account_id": expired["account"]["id"], "name": "Force won", "stage": "closed_won", "amount": "10"},
    )
    assert forced.status_code == 409
    _ = view


def _count(model) -> int:
    db = get_session()
    try:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)
    finally:
        db.close()
