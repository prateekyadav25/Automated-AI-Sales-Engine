"""Business invariants for the governed revenue journey."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session
from app.models.ai import AIApproval
from app.models.autonomy import EntityAutomationState
from app.models.execution import RevenueCohortSnapshot
from app.models.identity import DomainEvent, Tenant, User
from app.services.action_requests import classify_execution
from app.services.correlation import bound_correlation_id
from app.services.dispatcher import apply_approval_decision
from app.services.event_delivery import claim_next_event, fail_delivery
from app.services.revenue_ledger import retention_metrics
from tests.conftest import login


def test_correlation_ids_stay_within_the_column() -> None:
    raw = f"demo-board:expansion.detected:{uuid4()}"
    assert len(raw) > 64
    bounded = bound_correlation_id(raw)
    assert len(bounded) <= 64
    assert bound_correlation_id("short") == "short"


def test_unknown_action_is_not_a_successful_send(client: TestClient) -> None:
    login(client)
    db = get_session()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == "agrayian"))
        user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
        assert tenant is not None and user is not None
        row = AIApproval(
            tenant_id=tenant.id,
            created_by=user.id,
            action_level=2,
            action_type="mystery.effect",
            title="Unknown",
            status="pending",
            idempotency_key=f"mystery:{uuid4()}",
        )
        db.add(row)
        db.flush()
        apply_approval_decision(
            db,
            tenant_id=tenant.id,
            actor_id=user.id,
            row=row,
            decision="approve",
            note="",
        )
        assert "not executable" in row.decision_note
        assert classify_execution(row.decision_note) == "failed"
        db.rollback()
    finally:
        db.close()


def test_failed_event_stays_recoverable(client: TestClient) -> None:
    login(client)
    db = get_session()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == "agrayian"))
        user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
        assert tenant is not None and user is not None
        event = DomainEvent(
            tenant_id=tenant.id,
            event_type="test.boom",
            entity_type="lead",
            entity_id=str(uuid4()),
            correlation_id="test-boom",
        )
        db.add(event)
        db.flush()
        later = datetime.now(UTC) + timedelta(days=1)
        pending = db.scalars(
            select(DomainEvent).where(
                DomainEvent.tenant_id == tenant.id,
                DomainEvent.processed_at.is_(None),
                DomainEvent.id != event.id,
            )
        ).all()
        for row in pending:
            row.next_attempt_at = later
        db.flush()
        claimed = claim_next_event(db, tenant_id=tenant.id)
        assert claimed is not None and claimed.id == event.id
        fail_delivery(db, event, "handler failed", actor_id=user.id)
        assert event.processed_at is None
        assert event.delivery_status == "retry"
        assert event.attempts == 1
        again = claim_next_event(db, tenant_id=tenant.id)
        assert again is None or again.id != event.id
        db.rollback()
    finally:
        db.close()


def test_approved_discount_changes_the_quote_and_a_later_edit_is_stale(client: TestClient) -> None:
    headers = login(client)
    products = client.get("/api/v1/lifecycle/products", headers=headers).json()["data"]
    opps = client.get("/api/v1/opportunities", headers=headers).json()["data"]
    open_opp = next(row for row in opps if row["stage"] not in {"closed_won", "closed_lost"})
    created = client.post(
        "/api/v1/lifecycle/quotes",
        headers=headers,
        json={
            "opportunity_id": open_opp["id"],
            "discount_pct": 12,
            "tax_pct": 0,
            "lines": [{"product_id": products[0]["id"], "quantity": 1, "unit_price": "100"}],
        },
    )
    assert created.status_code == 200, created.text
    quote = created.json()["data"]
    assert quote["approval_required"] is True
    approvals = client.get("/api/v1/ai/approvals?page_size=100", headers=headers).json()["data"]
    approval = next(row for row in approvals if row["action_type"] == "quote.discount" and quote["id"] in row["payload_json"])
    decided = client.post(
        f"/api/v1/ai/approvals/{approval['id']}/decide",
        headers=headers,
        json={"decision": "approve", "note": "discount ok"},
    )
    assert decided.status_code == 200, decided.text
    current = client.get(f"/api/v1/lifecycle/quotes/{quote['id']}", headers=headers).json()["data"]
    assert current["status"] == "approved"
    assert current["approval_required"] is False
    original_total = current["total"]
    edited = client.post(
        f"/api/v1/lifecycle/quotes/{quote['id']}/lines",
        headers=headers,
        json={"product_id": products[0]["id"], "quantity": 1},
    )
    assert edited.status_code == 200, edited.text
    draft = edited.json()["data"]
    assert draft["id"] != quote["id"]
    assert draft["status"] == "draft"
    assert draft["parent_quote_id"] == quote["id"]
    again = client.post(
        f"/api/v1/ai/approvals/{approval['id']}/decide",
        headers=headers,
        json={"decision": "approve", "note": "reuse"},
    )
    assert again.status_code == 200, again.text
    assert "already approved" in again.json()["data"]["decision_note"]
    after = client.get(f"/api/v1/lifecycle/quotes/{quote['id']}", headers=headers).json()["data"]
    assert after["status"] == "approved"
    assert after["total"] == original_total


def test_emergency_stop_blocks_social_before_the_publisher(client: TestClient, monkeypatch) -> None:
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("publisher ran during an emergency stop")

    monkeypatch.setattr("app.services.social.get_social_publisher", _forbidden)
    headers = login(client)
    stopped = client.patch("/api/v1/autonomy/settings", headers=headers, json={"emergency_stop": True})
    assert stopped.status_code == 200, stopped.text
    try:
        created = client.post(
            "/api/v1/social/posts",
            headers=headers,
            json={"channel": "linkedin", "body": "This must not leave the building."},
        )
        assert created.status_code == 200, created.text
        row = created.json()["data"]
        assert row["status"] == "blocked"
        assert row["is_mock"] is False
    finally:
        client.patch("/api/v1/autonomy/settings", headers=headers, json={"emergency_stop": False})


def test_retention_is_unavailable_without_a_cohort(client: TestClient) -> None:
    headers = login(client)
    metrics = client.get("/api/v1/workflow/retention", headers=headers)
    assert metrics.status_code == 200, metrics.text
    body = metrics.json()["data"]
    assert body["status"] == "unavailable"
    assert body["grr"] is None
    assert body["nrr"] is None


def test_retention_reconciles_churn_and_expansion(client: TestClient) -> None:
    login(client)
    db = get_session()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == "northline"))
        user = db.scalar(select(User).where(User.tenant_id == tenant.id))
        assert tenant is not None and user is not None
        db.add(
            RevenueCohortSnapshot(
                tenant_id=tenant.id,
                created_by=user.id,
                period="2026-01",
                opening_arr=1000,
                churn_arr=100,
                contraction_arr=50,
                expansion_arr=200,
            )
        )
        db.flush()
        metrics = retention_metrics(db, tenant.id)
        assert metrics["status"] == "measured"
        assert metrics["grr"] == 0.85
        assert metrics["nrr"] == 1.05
        db.rollback()
    finally:
        db.close()


def test_missing_grant_blocks_even_when_approval_is_disabled(client: TestClient) -> None:
    headers = login(client)
    current = client.get("/api/v1/autonomy/settings", headers=headers).json()["data"]
    patched = client.patch(
        "/api/v1/autonomy/settings",
        headers=headers,
        json={
            "email_approval_required": False,
            "minimum_lead_score": 0,
            "enabled": True,
            "quiet_hours_start": "00:00",
            "quiet_hours_end": "00:00",
        },
    )
    assert patched.status_code == 200, patched.text
    try:
        created = client.post(
            "/api/v1/leads",
            headers=headers,
            json={
                "first_name": "Grant",
                "last_name": "Gap",
                "email": f"grant.gap.{uuid4().hex[:8]}@example.com",
                "company_name": "Grant Gap",
                "consent_email": True,
            },
        )
        assert created.status_code == 200, created.text
        lead_id = created.json()["data"]["id"]
        db = get_session()
        try:
            state = db.scalar(select(EntityAutomationState).where(EntityAutomationState.entity_id == lead_id))
            assert state is not None
            assert state.blocked_reason == "scoped_grant_required"
            pending = db.scalar(
                select(AIApproval).where(
                    AIApproval.entity_id == lead_id,
                    AIApproval.action_type == "sequence.email.send",
                    AIApproval.status == "pending",
                )
            )
            assert pending is None
        finally:
            db.close()
    finally:
        client.patch(
            "/api/v1/autonomy/settings",
            headers=headers,
            json={
                "email_approval_required": current["email_approval_required"],
                "minimum_lead_score": current["minimum_lead_score"],
                "enabled": current["enabled"],
                "quiet_hours_start": current["quiet_hours_start"],
                "quiet_hours_end": current["quiet_hours_end"],
            },
        )


def test_command_centre_and_launch_answer_what_can_run(client: TestClient) -> None:
    headers = login(client)
    command = client.get("/api/v1/workflow/command", headers=headers)
    launch = client.get("/api/v1/workflow/launch", headers=headers)
    assert command.status_code == 200, command.text
    assert launch.status_code == 200, launch.text
    assert "steps" in launch.json()["data"]
    assert isinstance(command.json()["data"], list)


def test_invitation_and_deactivation(client: TestClient) -> None:
    headers = login(client)
    email = f"invite.{uuid4().hex[:8]}@agrayian.demo"
    invited = client.post(
        "/api/v1/workflow/invitations",
        headers=headers,
        json={"email": email, "role_name": "Read Only", "name": "Invited Person"},
    )
    assert invited.status_code == 200, invited.text
    payload = invited.json()["data"]
    accepted = client.post(
        f"/api/v1/workflow/invitations/{payload['id']}/accept",
        json={"token": payload["token"], "name": "Invited Person", "password": "Agrarian!Demo1"},
    )
    assert accepted.status_code == 200, accepted.text
    user_id = accepted.json()["data"]["id"]
    stopped = client.post(f"/api/v1/workflow/users/{user_id}/deactivate", headers=headers)
    assert stopped.status_code == 200, stopped.text
    denied = client.post("/api/v1/auth/login", json={"email": email, "password": "Agrarian!Demo1"})
    assert denied.status_code == 401


def test_unsupported_playbook_action_does_not_complete(client: TestClient) -> None:
    headers = login(client)
    created = client.post(
        "/api/v1/lifecycle/playbooks",
        headers=headers,
        json={
            "name": "Unsafe send",
            "trigger_event": "manual",
            "actions_json": '[{"type": "send_email"}]',
        },
    )
    assert created.status_code == 200, created.text
    accounts = client.get("/api/v1/accounts", headers=headers).json()["data"]
    ran = client.post(
        f"/api/v1/lifecycle/playbooks/{created.json()['data']['id']}/run",
        headers=headers,
        json={"entity_type": "account", "entity_id": accounts[0]["id"]},
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["data"]["status"] == "failed"


def test_ad_publish_without_an_approved_budget_does_not_spend(client: TestClient, monkeypatch) -> None:
    calls = {"create": 0}

    class _Ads:
        def create_campaign(self, *, name: str, objective: str, budget) -> object:
            _ = (name, objective, budget)
            calls["create"] += 1
            raise AssertionError("ads provider ran without an approved budget")

        def activate_campaign(self, *, external_id: str) -> object:
            _ = external_id
            return None

    monkeypatch.setattr("app.services.content.get_llm_provider", _llm)
    monkeypatch.setattr("app.services.content.get_ads_provider", lambda *_args, **_kwargs: _Ads())
    headers = login(client)
    profile = client.put(
        "/api/v1/content/profile",
        headers=headers,
        json={
            "company_name": "Northwind",
            "summary": "We help revenue teams keep one record from first touch to renewal.",
            "audience": "B2B revenue leaders",
            "website": "https://example.com",
            "proof": "",
            "capture_url": "https://example.com/capture/demo",
        },
    )
    assert profile.status_code == 200, profile.text
    product = client.post(
        "/api/v1/content/products",
        headers=headers,
        json={"sku": f"NOBUD-{uuid4().hex[:6]}", "name": "Unbudgeted", "description": "No plan."},
    )
    assert product.status_code == 200, product.text
    created = client.post(
        "/api/v1/content/generate",
        headers=headers,
        json={"product_id": product.json()["data"]["id"], "ad_channel": "linkedin"},
    )
    assert created.status_code == 200, created.text
    draft = next(row for row in created.json()["data"] if row["kind"] == "ad")
    published = client.post(f"/api/v1/content/drafts/{draft['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    body = published.json()["data"]
    assert body["status"] == "failed"
    assert "not an ad budget" in body["error"]
    assert calls["create"] == 0


def _llm(*_args, **_kwargs):
    from tests.test_content import STRUCTURED, _StubLLM

    return _StubLLM(STRUCTURED, is_mock=True)
