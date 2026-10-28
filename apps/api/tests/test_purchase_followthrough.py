"""Purchased onboarding, observed health, and reviewable retention. No external work."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.session import get_session
from app.models.autonomy import AutopilotSettings
from app.models.crm import Customer, Renewal, Task
from app.models.identity import DomainEvent
from app.models.integrations import EmailMessage
from app.models.lifecycle import DealPurchase, OnboardingMilestone, OnboardingPlan, Product
from app.models.operating_plan import DemoScope
from app.models.post_sale import Contract
from app.services.autopilot_settings import get_or_create_settings
from app.services.commercial_close import decide_close_won
from app.services.demo_guard import EXPIRED_BLOCK, PREPARED_BLOCK
from app.services.onboarding import reconcile_onboarding
from app.services.orchestrator import handle_event
from app.services.purchase_followthrough import hold_elapsed_items
from tests.conftest import login
from tests.test_commercial_close import _close, _ready

PRICE = "125000.50"
TOTAL = Decimal("250001.00")


def _user(client: TestClient, headers: dict) -> dict:
    return client.get("/api/v1/auth/me", headers=headers).json()["data"]["user"]


def _item(checklist: list[dict], key: str) -> dict:
    return next(row for row in checklist if row["template_key"] == key)


def _emails() -> int:
    db = get_session()
    try:
        return int(db.scalar(select(func.count()).select_from(EmailMessage)) or 0)
    finally:
        db.close()


def _ledger_closed(client: TestClient, headers: dict, bucket: str) -> Decimal:
    body = client.get("/api/v1/lifecycle/commercial-ledger", headers=headers).json()["data"]
    return Decimal(str(body[bucket].get("USD", {}).get("closed_won", "0")))


def test_purchase_onboarding_health_and_retention_stay_inside_the_record(client: TestClient) -> None:
    headers = login(client)
    emails = _emails()
    real_before = _ledger_closed(client, headers, "real")
    row = _ready(client, headers, name="Follow through", service_start=None, service_end=None)
    opportunity = client.get(f"/api/v1/opportunities/{row['opportunity']['id']}", headers=headers).json()["data"]
    assert Decimal(str(opportunity["amount"])) == Decimal("10.00")
    assert opportunity.get("currency", "") in {"", None}
    view = _close(client, headers, row)
    assert view["currency"] == "USD"
    assert Decimal(str(view["total"])) == TOTAL
    assert Decimal(str(view["total"])) != Decimal(str(opportunity["amount"]))
    assert view["external_released"] is False
    assert view["payment_status"] == ""
    assert view["activated"] is False
    assert view["onboarding_status"] == "open"
    checklist = view["checklist"]
    assert len(checklist) == 7
    assert _item(checklist, "information.billing")["status"] == "reviewed"
    assert _item(checklist, "information.service_dates")["status"] == "requested"
    assert view["onboarding_blocker"] == "Service dates"
    assert _item(checklist, "setup.access")["status"] == "blocked"
    assert _item(checklist, "delivery.verify")["status"] == "pending"
    assert _item(checklist, "completion.gate")["status"] == "blocked"
    assert _item(checklist, "notes.optional")["required"] is False
    assert all(item["owner_name"] for item in checklist)
    assert "Service start" in view["missing_information"]
    plan_id = view["onboarding_plan_id"]
    purchase_id = client.get(f"/api/v1/post-sale/customers/{view['customer_id']}", headers=headers).json()["data"]["purchases"][0]["id"]
    blocked = client.post(
        f"/api/v1/lifecycle/onboarding/{plan_id}/complete",
        headers=headers,
        json={"evidence": "Trying to finish without the service dates"},
    )
    assert blocked.status_code == 409
    assert "still open" in blocked.json()["detail"]
    upload = client.post(
        f"/api/v1/lifecycle/onboarding/{plan_id}/items/{_item(checklist, 'delivery.verify')['id']}/evidence",
        headers=headers,
        json={"note": "A file was uploaded", "source": "document"},
    )
    assert upload.status_code == 200, upload.text
    supplied = _item(upload.json()["data"]["checklist"], "delivery.verify")
    assert supplied["status"] == "supplied"
    assert supplied["review_state"] == "needs_review"
    still_blocked = client.post(
        f"/api/v1/lifecycle/onboarding/{plan_id}/complete",
        headers=headers,
        json={"evidence": "The upload is not a review"},
    )
    assert still_blocked.status_code == 409
    waived = client.post(
        f"/api/v1/lifecycle/onboarding/{plan_id}/items/{_item(checklist, 'information.service_dates')['id']}/waive",
        headers=headers,
        json={"reason": "The customer has not agreed dates. This does not invent a term."},
    )
    assert waived.status_code == 200, waived.text
    assert _item(waived.json()["data"]["checklist"], "information.service_dates")["waiver_reason"].startswith("The customer")
    for key in ("setup.access", "delivery.verify"):
        item_id = _item(waived.json()["data"]["checklist"], key)["id"]
        noted = client.post(
            f"/api/v1/lifecycle/onboarding/{plan_id}/items/{item_id}/evidence",
            headers=headers,
            json={"note": f"Operator note for {key}. Not provider-verified.", "source": "operator"},
        )
        assert noted.status_code == 200, noted.text
        reviewed = client.post(
            f"/api/v1/lifecycle/onboarding/{plan_id}/items/{item_id}/review",
            headers=headers,
            json={"note": "Reviewed against the purchased scope"},
        )
        assert reviewed.status_code == 200, reviewed.text
        assert _item(reviewed.json()["data"]["checklist"], key)["status"] == "reviewed"
    reviewed_setup = _item(reviewed.json()["data"]["checklist"], "setup.access")["status"]
    user = _user(client, headers)
    db = get_session()
    try:
        event = db.scalar(
            select(DomainEvent)
            .where(
                DomainEvent.tenant_id == UUID(user["tenant_id"]),
                DomainEvent.event_type == "commercial.onboarding_opened",
                DomainEvent.entity_id == row["opportunity"]["id"],
            )
            .order_by(DomainEvent.created_at.desc())
        )
        assert event is not None
        settings = get_or_create_settings(db, tenant_id=UUID(user["tenant_id"]), actor_id=UUID(user["id"]))
        settings.enabled = False
        db.commit()
        try:
            assert handle_event(db, event, actor_id=UUID(user["id"])) == "reconciled"
            db.commit()
        finally:
            fresh = db.get(AutopilotSettings, settings.id)
            if fresh is not None:
                fresh.enabled = True
                db.commit()
        setup = db.scalar(
            select(OnboardingMilestone).where(
                OnboardingMilestone.plan_id == UUID(plan_id),
                OnboardingMilestone.template_key == "setup.access",
            )
        )
        assert setup is not None
        assert setup.status == reviewed_setup
        notes = db.scalar(
            select(OnboardingMilestone).where(
                OnboardingMilestone.plan_id == UUID(plan_id),
                OnboardingMilestone.template_key == "notes.optional",
            )
        )
        assert notes is not None
        notes.due_date = datetime(2020, 1, 1, tzinfo=UTC).date()
        db.commit()
        plan = db.get(OnboardingPlan, UUID(plan_id))
        assert plan is not None
        assert hold_elapsed_items(db, plan) == 1
        assert notes.status == "pending"
        customer = db.get(Customer, UUID(view["customer_id"]))
        assert customer is not None
        reconcile_onboarding(db, tenant_id=UUID(user["tenant_id"]), actor_id=UUID(user["id"]), customer=customer)
        db.commit()
        assert customer.lifecycle_state == "NEW_CUSTOMER"
        assert customer.status == "onboarding"
    finally:
        db.close()
    done = client.post(
        f"/api/v1/lifecycle/onboarding/{plan_id}/complete",
        headers=headers,
        json={"evidence": "Required steps were reviewed or waived for this purchase."},
    )
    assert done.status_code == 200, done.text
    body = done.json()["data"]
    assert body["onboarding_status"] == "completed"
    assert body["payment_status"] == ""
    assert body["external_released"] is False
    assert _item(body["checklist"], "notes.optional")["status"] == "pending"
    assert body["completions"][0]["waived"] == ["information.service_dates"]
    assert body["completions"][0]["actor_name"]
    again = client.post(
        f"/api/v1/lifecycle/onboarding/{plan_id}/complete",
        headers=headers,
        json={"evidence": "Second completion must not add another decision."},
    )
    assert again.status_code == 200, again.text
    assert len(again.json()["data"]["completions"]) == 1
    customer_body = client.get(f"/api/v1/post-sale/customers/{view['customer_id']}", headers=headers).json()["data"]
    assert customer_body["commercial_freshness"] == "fixture"
    assert customer_body["customer"]["status"] == "onboarding"
    assert customer_body["customer"]["lifecycle_state"] == "NEW_CUSTOMER"
    assert customer_body["renewal_date"] is None
    assert customer_body["health_explanation"]["score"] is None
    assert customer_body["health_explanation"]["status"] == "insufficient_evidence"
    assert customer_body["health_total"] is None
    assert customer_body["health_data_coverage"] is None
    assert customer_body["health_version"] == ""
    assert customer_body["usage_freshness"] == "NOT_CONNECTED"
    refused = client.post(f"/api/v1/lifecycle/success/health/{view['customer_id']}", headers=headers)
    assert refused.status_code == 409
    missing = client.post(
        f"/api/v1/lifecycle/purchases/{purchase_id}/health",
        headers=headers,
        json={
            "signal_type": "usage",
            "period_key": "2026-11",
            "freshness": "missing",
            "coverage": "insufficient",
            "value_numeric": "0",
            "provenance": "operator",
        },
    )
    assert missing.status_code == 200, missing.text
    usage = missing.json()["data"]["health"]["signals"][0]
    assert usage["value_numeric"] is None
    assert usage["value_text"] == ""
    assert missing.json()["data"]["health"]["score"] is None
    assert missing.json()["data"]["health"]["status"] == "insufficient_evidence"
    assert missing.json()["data"]["retention_tasks"] == []
    payment = client.post(
        f"/api/v1/lifecycle/purchases/{purchase_id}/health",
        headers=headers,
        json={
            "signal_type": "payment",
            "period_key": "2026-11",
            "freshness": "fresh",
            "coverage": "sufficient",
            "provenance": "provider",
            "value_text": "unpaid",
        },
    )
    assert payment.status_code == 200, payment.text
    invoice = next(row for row in payment.json()["data"]["health"]["signals"] if row["signal_type"] == "payment")
    assert invoice["provenance"] == "unsupported"
    assert invoice["value_numeric"] is None
    assert invoice["value_text"] == ""
    assert "not an unpaid invoice" in invoice["limitations"]
    assert payment.json()["data"]["payment_status"] == ""
    check_in = client.post(
        f"/api/v1/lifecycle/purchases/{purchase_id}/health",
        headers=headers,
        json={
            "signal_type": "check_in",
            "period_key": "2026-11",
            "freshness": "fresh",
            "coverage": "sufficient",
            "value_text": "Ask whether the purchased setup needs a review",
            "evidence": "Operator note",
            "provenance": "operator",
        },
    )
    assert check_in.status_code == 200, check_in.text
    tasks = check_in.json()["data"]["retention_tasks"]
    assert len(tasks) == 1
    assert "check-in" in tasks[0]["title"].lower()
    assert "not marketing consent" in tasks[0]["description"]
    assert "No message" in tasks[0]["description"]
    repeat = client.post(
        f"/api/v1/lifecycle/purchases/{purchase_id}/health",
        headers=headers,
        json={"signal_type": "check_in", "period_key": "2026-11", "freshness": "fresh", "coverage": "sufficient", "value_text": "same"},
    )
    assert len(repeat.json()["data"]["retention_tasks"]) == 1
    assert repeat.json()["data"]["retention_tasks"][0]["id"] == tasks[0]["id"]
    issue = client.post(
        f"/api/v1/lifecycle/purchases/{purchase_id}/health",
        headers=headers,
        json={"signal_type": "service_issue", "period_key": "2026-11", "freshness": "fresh", "coverage": "sufficient", "value_text": "Access is blocked"},
    )
    assert len(issue.json()["data"]["retention_tasks"]) == 2
    later = client.post(
        f"/api/v1/lifecycle/purchases/{purchase_id}/health",
        headers=headers,
        json={"signal_type": "check_in", "period_key": "2026-12", "freshness": "fresh", "coverage": "sufficient", "value_text": "Later period"},
    )
    assert len(later.json()["data"]["retention_tasks"]) == 3
    assert all("Renewal preparation" not in task["title"] for task in later.json()["data"]["retention_tasks"])
    db = get_session()
    try:
        later_task = db.scalar(select(Task).where(Task.title.contains("2026-12"), Task.entity_id == purchase_id))
        assert later_task is not None
        later_task.status = "cancelled"
        db.commit()
        customer = db.get(Customer, UUID(view["customer_id"]))
        assert customer is not None
        assert customer.activated_at is None
        assert customer.onboarding_completed_at is None
        assert customer.go_live_at is None
        renewals = int(
            db.scalar(select(func.count()).select_from(Renewal).where(Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None))) or 0
        )
        contracts = int(db.scalar(select(func.count()).select_from(Contract).where(Contract.customer_id == customer.id)) or 0)
        assert renewals == 0
        assert contracts == 0
        purchase = db.get(DealPurchase, UUID(purchase_id))
        assert purchase is not None
        snapshot = purchase.snapshot_json
        event = db.scalar(
            select(DomainEvent).where(
                DomainEvent.event_type == "purchase.onboarding_completed",
                DomainEvent.entity_id == plan_id,
            )
        )
        assert event is not None
        assert handle_event(db, event, actor_id=UUID(user["id"])) == "preserved"
        db.commit()
        assert db.get(OnboardingPlan, UUID(plan_id)).status == "completed"
    finally:
        db.close()
    replay = client.post(
        f"/api/v1/lifecycle/purchases/{purchase_id}/health",
        headers=headers,
        json={"signal_type": "check_in", "period_key": "2026-12", "freshness": "fresh", "coverage": "sufficient", "value_text": "Later period"},
    )
    replayed = next(task for task in replay.json()["data"]["retention_tasks"] if "2026-12" in task["title"])
    assert replayed["status"] == "cancelled"
    assert len(replay.json()["data"]["retention_tasks"]) == 3
    db = get_session()
    try:
        purchase = db.get(DealPurchase, UUID(purchase_id))
        assert purchase is not None
        assert purchase.snapshot_json == snapshot
        contact_email = row["contact"]["email"]
        assert contact_email
    finally:
        db.close()
    corrected = client.post(
        f"/api/v1/lifecycle/onboarding/{plan_id}/correct",
        headers=headers,
        json={"reason": "The waiver note needed a clearer owner."},
    )
    assert corrected.status_code == 200, corrected.text
    history = corrected.json()["data"]["completions"]
    assert [item["action"] for item in history] == ["completed", "corrected"]
    assert corrected.json()["data"]["onboarding_status"] == "open"
    readonly = login(client, "readonly@agrayian.demo")
    denied = client.post(
        f"/api/v1/lifecycle/onboarding/{plan_id}/complete",
        headers=readonly,
        json={"evidence": "Readonly cannot complete"},
    )
    assert denied.status_code == 403
    northline = login(client, "admin@northline.demo")
    assert client.get(f"/api/v1/lifecycle/purchases/{purchase_id}/followthrough", headers=northline).status_code == 404
    assert client.post(
        f"/api/v1/lifecycle/purchases/{purchase_id}/health",
        headers=northline,
        json={"signal_type": "check_in", "period_key": "2026-11", "value_text": "other tenant"},
    ).status_code == 404
    assert _emails() == emails
    assert _ledger_closed(client, headers, "real") == real_before


def test_one_time_purchase_has_no_renewal_and_a_second_purchase_keeps_its_own(client: TestClient) -> None:
    headers = login(client)
    first = _ready(client, headers, name="First purchase", cadence="annual", service_start="2026-11-01", service_end="2027-11-01")
    db = get_session()
    try:
        product = db.get(Product, UUID(first["product"]["id"]))
        assert product is not None
        product.name = "Renamed after quote"
        product.kind = "subscription"
        db.commit()
    finally:
        db.close()
    opened = _close(client, headers, first)
    assert opened["customer_facing_name"].startswith("Northline Desk")
    assert "Renamed" not in opened["customer_facing_name"]
    customer_id = opened["customer_id"]
    first_body = client.get(f"/api/v1/post-sale/customers/{customer_id}", headers=headers).json()["data"]
    follow = client.get(f"/api/v1/lifecycle/purchases/{first_body['purchases'][0]['id']}/followthrough", headers=headers)
    assert follow.status_code == 200, follow.text
    assert follow.json()["data"]["product_kind"] == "one_time"
    assert follow.json()["data"]["renewal_recorded"] is False
    assert "No renewal date" in follow.json()["data"]["renewal_note"]
    assert all("Renewal preparation" not in task["title"] for task in follow.json()["data"]["retention_tasks"])
    first_purchase = follow.json()["data"]["purchase_id"]
    product = client.post(
        "/api/v1/lifecycle/products",
        headers=headers,
        json={"sku": "SUBSECOND", "name": "Second subscription", "kind": "subscription", "list_price": PRICE, "currency": "USD"},
    ).json()["data"]
    opportunity = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"account_id": first["account"]["id"], "name": "Second purchase", "stage": "commit", "amount": "20.00"},
    ).json()["data"]
    created = client.post(
        "/api/v1/lifecycle/quotes",
        headers=headers,
        json={
            "opportunity_id": opportunity["id"],
            "scope_text": "Second scope",
            "billing_cadence": "annual",
            "service_start": "2027-12-01",
            "service_end": "2028-12-01",
            "valid_until": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
            "lines": [{"product_id": product["id"], "quantity": 1, "unit_price": PRICE}],
        },
    )
    assert created.status_code == 200, created.text
    quote_id = created.json()["data"]["id"]
    assert client.post(f"/api/v1/lifecycle/quotes/{quote_id}/issue", headers=headers).status_code == 200
    assert client.post(
        f"/api/v1/workflow/quotes/{quote_id}/accept",
        headers=headers,
        json={"contact_id": first["contact"]["id"], "relationship": "economic_buyer", "source": "manual", "evidence": "Second acceptance"},
    ).status_code == 200
    second = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/close-won",
        headers=headers,
        json={"quote_id": quote_id, "note": "Second purchase"},
    )
    assert second.status_code == 200, second.text
    customer = client.get(f"/api/v1/post-sale/customers/{opened['customer_id']}", headers=headers).json()["data"]
    assert len(customer["purchases"]) == 2
    assert customer["purchases"][0]["id"] == first_purchase
    assert customer["purchases"][0]["scope_text"] == "One desk router"
    assert customer["purchases"][1]["scope_text"] == "Second scope"
    assert customer["purchases"][0]["product_kind"] == "one_time"
    assert customer["purchases"][1]["product_kind"] == "subscription"
    assert len(customer["purchases"][0]["checklist"]) == 7
    assert len(customer["purchases"][1]["checklist"]) == 7
    renewal_tasks = [task for task in customer["retention_tasks"] if task["title"].startswith("Renewal preparation")]
    assert len(renewal_tasks) == 1
    assert "does not renew" in renewal_tasks[0]["description"]
    assert customer["renewal_date"] is None
    db = get_session()
    try:
        customer_row = db.get(Customer, UUID(opened["customer_id"]))
        assert customer_row is not None
        assert db.scalar(select(func.count()).select_from(Renewal).where(Renewal.customer_id == customer_row.id, Renewal.deleted_at.is_(None))) == 0
        purchase = db.get(DealPurchase, UUID(customer["purchases"][1]["id"]))
        assert purchase is not None
        assert purchase.payment_status == ""
        assert "125000.50" in purchase.snapshot_json
    finally:
        db.close()


def test_replay_does_not_duplicate_onboarding_and_scopes_release_nothing(client: TestClient) -> None:
    headers = login(client)
    row = _ready(client, headers, name="Replay purchase")
    user = _user(client, headers)
    db = get_session()
    try:
        decide_close_won(
            db,
            tenant_id=UUID(user["tenant_id"]),
            actor_id=UUID(user["id"]),
            opportunity_id=UUID(row["opportunity"]["id"]),
            quote_id=UUID(row["quote"]["id"]),
            note="First attempt",
        )
        db.flush()
        purchase = db.scalar(select(DealPurchase).where(DealPurchase.opportunity_id == UUID(row["opportunity"]["id"])))
        assert purchase is not None
        first = int(
            db.scalar(select(func.count()).select_from(OnboardingMilestone).where(OnboardingMilestone.plan_id == purchase.onboarding_plan_id)) or 0
        )
        db.rollback()
        decide_close_won(
            db,
            tenant_id=UUID(user["tenant_id"]),
            actor_id=UUID(user["id"]),
            opportunity_id=UUID(row["opportunity"]["id"]),
            quote_id=UUID(row["quote"]["id"]),
            note="Recovered attempt",
        )
        db.commit()
        purchase = db.scalar(select(DealPurchase).where(DealPurchase.opportunity_id == UUID(row["opportunity"]["id"])))
        assert purchase is not None
        second = int(
            db.scalar(select(func.count()).select_from(OnboardingMilestone).where(OnboardingMilestone.plan_id == purchase.onboarding_plan_id)) or 0
        )
        assert first == second == 7
        plans = int(
            db.scalar(select(func.count()).select_from(OnboardingPlan).where(OnboardingPlan.opportunity_id == UUID(row["opportunity"]["id"]))) or 0
        )
        assert plans == 1
    finally:
        db.close()
    replayed = _close(client, headers, row)
    assert len(replayed["checklist"]) == 7
    emails = _emails()
    scope_id = None
    db = get_session()
    try:
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
        customer = client.get(f"/api/v1/post-sale/customers/{replayed['customer_id']}", headers=headers).json()["data"]
        purchase_id = customer["purchases"][0]["id"]
        held = client.get(f"/api/v1/lifecycle/purchases/{purchase_id}/followthrough", headers=headers)
        assert held.status_code == 200, held.text
        assert held.json()["data"]["external_released"] is False
        assert held.json()["data"]["external_block"] == PREPARED_BLOCK
        db = get_session()
        try:
            current = db.get(DemoScope, scope_id)
            assert current is not None
            current.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
            db.commit()
        finally:
            db.close()
        expired = client.get(f"/api/v1/lifecycle/purchases/{purchase_id}/followthrough", headers=headers)
        assert expired.json()["data"]["external_released"] is False
        assert expired.json()["data"]["external_block"] == EXPIRED_BLOCK
        assert _emails() == emails
    finally:
        db = get_session()
        try:
            current = db.get(DemoScope, scope_id)
            if current is not None:
                db.delete(current)
                db.commit()
        finally:
            db.close()


def test_operator_recorded_provenance_is_not_live_or_provider_verified(client: TestClient) -> None:
    headers = login(client)
    row = _ready(client, headers, name="Provenance")
    view = _close(client, headers, row)
    customer = client.get(f"/api/v1/post-sale/customers/{view['customer_id']}", headers=headers).json()["data"]
    assert customer["commercial_freshness"] == "fixture"
    purchase_id = customer["purchases"][0]["id"]
    db = get_session()
    try:
        purchase = db.get(DealPurchase, UUID(purchase_id))
        assert purchase is not None
        purchase.fixture = False
        db.commit()
    finally:
        db.close()
    try:
        recorded = client.get(f"/api/v1/post-sale/customers/{view['customer_id']}", headers=headers).json()["data"]
        assert recorded["commercial_freshness"] == "operator_recorded"
        assert recorded["commercial_freshness"] != "LIVE"
        assert recorded["purchases"][0]["provenance"] == "operator_recorded"
    finally:
        db = get_session()
        try:
            purchase = db.get(DealPurchase, UUID(purchase_id))
            if purchase is not None:
                purchase.fixture = True
                db.commit()
        finally:
            db.close()
