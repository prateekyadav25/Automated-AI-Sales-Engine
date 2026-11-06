"""Meta native lead-form ingestion with fake Graph responses.

No live Meta, LinkedIn, email, or discovery call is made. A prepared
demonstration does not open a Graph client.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import get_session
from app.db.tenant_context import set_tenant_context
from app.models.acquisition import InboundCapture
from app.models.ai import AIApproval
from app.models.crm import Lead, Task
from app.models.identity import Tenant
from app.models.lead_form import LeadFormBinding, LeadFormReceipt
from app.models.lifecycle import Product, SequenceEnrollment
from app.models.operating_plan import DemoScope, OperatingPlan
from app.services.assessment import latest_decision
from app.services.demo_guard import PREPARED_BLOCK
from app.services.lead_forms import (
    POSTING_TOKEN_UNUSED,
    REVIEW_PERMISSION,
    accept_leadgen_notification,
    bind_lead_form,
    process_due_lead_receipts,
)
from tests.test_organic_acquisition import _close_scopes, _user

PAGE = "123123123"
FORM = "12312312312"
EMAIL = "meta-form-fixture@example.com"
AD = "99887766"
CAMPAIGN = "55443322"
PERMISSIONS = {
    "answer_enquiry": {
        "source": "field",
        "question": "may_we_reply",
        "yes_values": ["yes"],
        "meaning": "Permission to answer this enquiry by email.",
    },
    "marketing_sequence": {
        "source": "field",
        "question": "marketing_updates",
        "yes_values": ["yes"],
        "meaning": "Permission for a marketing sequence. A yes does not enroll a sequence.",
    },
    "calls": {
        "source": "disclaimer",
        "question": "call_consent",
        "yes_values": ["1", "yes"],
        "meaning": "Permission for a phone call. A yes does not place a call.",
    },
}


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls = 0
        self.tokens: list[str] = []

    def get(self, url: str, params: dict) -> _Response:
        self.calls += 1
        self.tokens.append(str(params.get("access_token") or ""))
        assert str(params.get("fields") or "")
        assert url
        return self.responses.pop(0)


def _notice(lead_id: str, *, ad: str = "", tenant_id: str = "00000000-0000-0000-0000-000000000099") -> dict:
    value: dict = {"leadgen_id": lead_id, "page_id": PAGE, "form_id": FORM, "created_time": 1440120384}
    if ad:
        value["ad_id"] = ad
        value["adgroup_id"] = "adset-1"
    return {
        "object": "page",
        "entry": [{"id": PAGE, "time": 1440120384, "changes": [{"field": "leadgen", "value": value}]}],
        "tenant_id": tenant_id,
    }


def _detail(lead_id: str, answers: dict[str, str], *, ad: str = "", campaign: str = "", disclaimer: list | None = None) -> dict:
    payload: dict = {
        "id": lead_id,
        "created_time": "2015-02-28T08:49:14+0000",
        "form_id": FORM,
        "field_data": [{"name": name, "values": [value]} for name, value in answers.items()],
    }
    if ad:
        payload["ad_id"] = ad
    if campaign:
        payload["campaign_id"] = campaign
    if disclaimer is not None:
        payload["custom_disclaimer_responses"] = disclaimer
    return payload


def _workspace(db):
    user = _user(db)
    tenant_id = user.tenant_id
    _close_scopes(db, tenant_id)
    product = Product(
        tenant_id=tenant_id,
        created_by=user.id,
        sku="DESK",
        name="One-time setup, under 200 employees",
        kind="one_time",
        list_price=Decimal("300000"),
        currency="INR",
        description="A desk for a company under 200 employees.",
    )
    db.add(product)
    db.flush()
    plan = OperatingPlan(
        tenant_id=tenant_id,
        created_by=user.id,
        product_id=product.id,
        channel="facebook",
        status="running",
        audience="Operators",
    )
    db.add(plan)
    db.flush()
    db.add(
        DemoScope(
            tenant_id=tenant_id,
            created_by=user.id,
            plan_id=plan.id,
            channel="facebook",
            status="prepared",
            expires_at=datetime.now(UTC) + timedelta(days=2),
            allowed_actions=json.dumps({"email.acknowledge": 1}),
        )
    )
    db.flush()
    return user, plan


def _bind(db, user, plan, *, page: str = PAGE, form: str = FORM) -> LeadFormBinding:
    return bind_lead_form(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        page_id=page,
        form_id=form,
        operating_plan_id=plan.id,
        form_purpose="Ask for a product walkthrough",
        permission_questions=PERMISSIONS,
    )


def _lead(db, tenant_id) -> Lead | None:
    return db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.email == EMAIL, Lead.deleted_at.is_(None)))


def _count(db, model, *where) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def test_verified_notification_creates_one_acknowledgement(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        user, plan = _workspace(db)
        _bind(db, user, plan)
        lead_id = "leadgen-journey"
        other_tenant = str(uuid4())
        assert accept_leadgen_notification(db, _notice(lead_id, ad=AD, tenant_id=other_tenant))["accepted"] == 1
        graph = _Client([_Response(200, _detail(lead_id, {
            "full_name": "Fixture Person",
            "email": EMAIL,
            "may_we_reply": "yes",
            "marketing_updates": "no",
        }, ad=AD, campaign=CAMPAIGN, disclaimer=[{"checkbox_key": "call_consent", "is_checked": ""}]))])
        assert process_due_lead_receipts(db, client=graph) == 1
        lead = _lead(db, user.tenant_id)
        assert lead is not None
        assert lead.tenant_id == user.tenant_id
        assert str(lead.tenant_id) != other_tenant
        assert lead.source == "meta_lead_form"
        assert lead.ad_id == AD
        assert lead.operating_plan_id == plan.id
        assert lead.notes == ""
        assert lead.consent_email is True
        decision = latest_decision(db, tenant_id=user.tenant_id, lead_id=lead.id)
        assert decision is not None
        assert decision.response_eligible is True
        assert decision.outbound_eligible is False
        assert decision.not_a_fit is False
        assert _count(db, AIApproval, AIApproval.entity_id == str(lead.id), AIApproval.action_type == "email.acknowledge", AIApproval.deleted_at.is_(None)) == 1
        assert _count(db, AIApproval, AIApproval.entity_id == str(lead.id), AIApproval.action_type == "sequence.email.send", AIApproval.deleted_at.is_(None)) == 0
        assert _count(db, SequenceEnrollment, SequenceEnrollment.lead_id == lead.id, SequenceEnrollment.deleted_at.is_(None)) == 0
        receipt = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == lead_id))
        assert receipt is not None
        assert receipt.status == "processed"
        assert receipt.attribution == "ad"
        assert receipt.provider_campaign_id == CAMPAIGN
        assert graph.calls == 1
        assert graph.tokens == ["fixture-lead-token"]
        capture = db.get(InboundCapture, receipt.capture_id)
        assert capture is not None
        assert capture.request_note == ""
        questions = json.loads(receipt.permission_json)["questions"]
        assert questions[0]["granted"] is True
        assert questions[1]["granted"] is False
        assert questions[2]["granted"] is False
    finally:
        db.rollback()
        db.close()


def test_duplicate_delivery_and_worker_recovery_do_not_duplicate(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        user, plan = _workspace(db)
        _bind(db, user, plan)
        lead_id = "leadgen-replay"
        assert accept_leadgen_notification(db, _notice(lead_id, ad=AD))["accepted"] == 1
        assert accept_leadgen_notification(db, _notice(lead_id, ad=AD))["duplicate"] == 1
        assert _count(db, LeadFormReceipt, LeadFormReceipt.provider_lead_id == lead_id) == 1
        receipt = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == lead_id))
        assert receipt is not None
        receipt.status = "retrieving"
        db.flush()
        graph = _Client([_Response(200, _detail(lead_id, {"email": EMAIL, "full_name": "Fixture Person", "may_we_reply": "yes"}, ad=AD))])
        process_due_lead_receipts(db, client=graph)
        process_due_lead_receipts(db, client=graph)
        lead = _lead(db, user.tenant_id)
        assert lead is not None
        assert _count(db, InboundCapture, InboundCapture.lead_id == lead.id, InboundCapture.email == EMAIL) == 1
        assert _count(db, AIApproval, AIApproval.entity_id == str(lead.id), AIApproval.action_type == "email.acknowledge", AIApproval.deleted_at.is_(None)) == 1
        assert _count(db, Task, Task.entity_id == str(lead.id), Task.title == REVIEW_PERMISSION, Task.deleted_at.is_(None)) == 0
        assert graph.calls == 1
    finally:
        db.rollback()
        db.close()


def test_second_enquiry_reuses_the_person_and_keeps_first_touch(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        user, first_plan = _workspace(db)
        binding = _bind(db, user, first_plan)
        first = "leadgen-first"
        second = "leadgen-second"
        accept_leadgen_notification(db, _notice(first, ad="111"))
        process_due_lead_receipts(db, client=_Client([_Response(200, _detail(first, {"email": EMAIL, "full_name": "Fixture Person", "may_we_reply": "yes"}, ad="111"))]))
        lead = _lead(db, user.tenant_id)
        assert lead is not None
        later = OperatingPlan(tenant_id=user.tenant_id, created_by=user.id, product_id=first_plan.product_id, channel="facebook", status="running")
        db.add(later)
        db.flush()
        binding.operating_plan_id = later.id
        db.flush()
        accept_leadgen_notification(db, _notice(second, ad="222"))
        process_due_lead_receipts(db, client=_Client([_Response(200, _detail(second, {"email": EMAIL, "full_name": "Fixture Person", "may_we_reply": "yes"}, ad="222"))]))
        db.refresh(lead)
        captures = db.scalars(select(InboundCapture).where(InboundCapture.tenant_id == user.tenant_id, InboundCapture.email == EMAIL)).all()
        assert len(captures) == 2
        assert lead.ad_id == "111"
        assert lead.operating_plan_id == first_plan.id
        assert {row.ad_id for row in captures} == {"111", "222"}
        assert _count(db, Lead, Lead.tenant_id == user.tenant_id, Lead.email == EMAIL, Lead.deleted_at.is_(None)) == 1
        assert _count(db, AIApproval, AIApproval.entity_id == str(lead.id), AIApproval.action_type == "sequence.email.send", AIApproval.deleted_at.is_(None)) == 0
    finally:
        db.rollback()
        db.close()


def test_invalid_signature_and_unknown_or_cross_tenant_forms(client: TestClient, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "meta_app_secret", "meta-app-secret")
    monkeypatch.setattr(settings, "meta_webhook_verify_token", "meta-verify")
    body = json.dumps(
        {"object": "page", "entry": [{"id": "unmapped-page", "changes": [{"field": "leadgen", "value": {"leadgen_id": "leadgen-signed", "page_id": "unmapped-page", "form_id": "unmapped-form", "created_time": 1}}]}]}
    ).encode()
    bad = client.post("/api/v1/webhooks/meta/leadgen", content=body, headers={"X-Hub-Signature-256": "sha256=nope"})
    assert bad.status_code == 401
    challenge = client.get("/api/v1/webhooks/meta/leadgen", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1158201444"})
    assert challenge.status_code == 403
    ok = client.get("/api/v1/webhooks/meta/leadgen", params={"hub.mode": "subscribe", "hub.verify_token": "meta-verify", "hub.challenge": "1158201444"})
    assert ok.status_code == 200
    assert ok.text == "1158201444"
    signature = "sha256=" + hmac.new(b"meta-app-secret", body, hashlib.sha256).hexdigest()
    stored = client.post("/api/v1/webhooks/meta/leadgen", content=body, headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"})
    assert stored.status_code == 200
    assert stored.json()["accepted"] == 1
    cleanup = get_session()
    signed = cleanup.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-signed"))
    assert signed is not None and signed.status == "received"
    cleanup.delete(signed)
    cleanup.commit()
    cleanup.close()
    db = get_session()
    try:
        user, plan = _workspace(db)
        accept_leadgen_notification(db, {"object": "page", "entry": [{"id": "unknown-page", "changes": [{"field": "leadgen", "value": {"leadgen_id": "leadgen-unknown", "page_id": "unknown-page", "form_id": "unknown-form", "created_time": 1, "tenant_id": str(user.tenant_id)}}]}]})
        graph = _Client([_Response(200, _detail("leadgen-unknown", {"email": EMAIL}))])
        process_due_lead_receipts(db, client=graph)
        unknown = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-unknown"))
        assert unknown is not None
        assert unknown.status == "needs_review"
        assert unknown.tenant_id is None
        assert unknown.lead_id is None
        assert graph.calls == 0
        other = Tenant(name="Other workspace", slug=f"other-{uuid4().hex[:8]}", operating_mode="DEMO")
        db.add(other)
        db.flush()
        other_plan = OperatingPlan(tenant_id=other.id, channel="facebook", status="running")
        db.add(other_plan)
        db.flush()
        _bind(db, user, plan, page="page-shared", form="form-shared")
        db.add(
            LeadFormBinding(
                tenant_id=other.id,
                provider="meta",
                page_id="page-shared",
                form_id="form-shared",
                operating_plan_id=other_plan.id,
                status="active",
            )
        )
        db.flush()
        accept_leadgen_notification(db, {"object": "page", "entry": [{"id": "page-shared", "changes": [{"field": "leadgen", "value": {"leadgen_id": "leadgen-shared", "page_id": "page-shared", "form_id": "form-shared", "created_time": 1}}]}]})
        raising = _Client([_Response(200, {"id": "leadgen-shared"})])
        process_due_lead_receipts(db, client=raising)
        shared = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-shared"))
        assert shared is not None
        assert shared.status == "needs_review"
        assert shared.lead_id is None
        assert raising.calls == 0
    finally:
        db.rollback()
        db.close()


def test_missing_email_note_and_permission_are_kept(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        user, plan = _workspace(db)
        _bind(db, user, plan)
        accept_leadgen_notification(db, _notice("leadgen-no-email", ad=AD))
        process_due_lead_receipts(db, client=_Client([_Response(200, _detail("leadgen-no-email", {"full_name": "Fixture Person"}, ad=AD))]))
        missing_email = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-no-email"))
        assert missing_email is not None and missing_email.lead_id is None and missing_email.status == "needs_review"

        accept_leadgen_notification(db, _notice("leadgen-no-note"))
        process_due_lead_receipts(db, client=_Client([_Response(200, _detail("leadgen-no-note", {"email": "note-free@example.com", "full_name": "Fixture Person", "may_we_reply": "yes"}))]))
        noted = db.scalar(select(Lead).where(Lead.email == "note-free@example.com", Lead.deleted_at.is_(None)))
        assert noted is not None
        assert noted.notes == ""
        assert noted.ad_id == ""
        no_note = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-no-note"))
        assert no_note is not None and no_note.attribution == "unattributed"
        capture = db.get(InboundCapture, no_note.capture_id)
        assert capture is not None and capture.request_note == ""
        assert _count(db, AIApproval, AIApproval.entity_id == str(noted.id), AIApproval.action_type == "email.acknowledge", AIApproval.deleted_at.is_(None)) == 1

        accept_leadgen_notification(db, _notice("leadgen-no-permission", ad=AD))
        process_due_lead_receipts(db, client=_Client([_Response(200, _detail("leadgen-no-permission", {"email": "no-permission@example.com", "full_name": "Fixture Person"}, ad=AD))]))
        held = db.scalar(select(Lead).where(Lead.email == "no-permission@example.com", Lead.deleted_at.is_(None)))
        assert held is not None
        assert held.consent_email is False
        assert held.company_name == ""
        decision = latest_decision(db, tenant_id=user.tenant_id, lead_id=held.id)
        assert decision is not None and decision.not_a_fit is False and decision.outbound_eligible is False
        assert _count(db, Task, Task.entity_id == str(held.id), Task.title == REVIEW_PERMISSION, Task.deleted_at.is_(None)) == 1
        assert _count(db, AIApproval, AIApproval.entity_id == str(held.id), AIApproval.action_type == "email.acknowledge", AIApproval.deleted_at.is_(None)) == 0
        assert _count(db, AIApproval, AIApproval.entity_id == str(held.id), AIApproval.action_type == "sequence.email.send", AIApproval.deleted_at.is_(None)) == 0
    finally:
        db.rollback()
        db.close()


def test_provider_permission_and_rate_limit_keep_the_receipt(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        user, plan = _workspace(db)
        _bind(db, user, plan)
        accept_leadgen_notification(db, _notice("leadgen-denied", ad=AD))
        denied = _Client([_Response(403, {"error": {"code": 200, "message": "Requires leads_retrieval"}}), _Response(200, {"id": "leadgen-denied"})])
        process_due_lead_receipts(db, client=denied)
        process_due_lead_receipts(db, client=denied)
        row = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-denied"))
        assert row is not None
        assert row.status == "permission_denied", row.error
        assert row.lead_id is None
        assert denied.calls == 1

        accept_leadgen_notification(db, _notice("leadgen-limited", ad=AD))
        limited = _Client([
            _Response(429, {"error": {"code": 4, "message": "Application request limit reached"}}),
            _Response(200, _detail("leadgen-limited", {"email": "limited@example.com", "full_name": "Fixture Person", "may_we_reply": "yes"}, ad=AD)),
        ])
        process_due_lead_receipts(db, client=limited)
        waiting = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-limited"))
        assert waiting is not None and waiting.status == "rate_limited" and waiting.lead_id is None
        process_due_lead_receipts(db, client=limited)
        db.refresh(waiting)
        assert waiting.status == "processed"
        assert db.scalar(select(Lead).where(Lead.email == "limited@example.com", Lead.deleted_at.is_(None))) is not None
        assert limited.calls == 2
    finally:
        db.rollback()
        db.close()


def test_prepared_scope_and_posting_token_make_no_live_request(client: TestClient, monkeypatch) -> None:
    _ = client
    calls: list[str] = []

    def _live(token: str):
        calls.append(token)
        raise AssertionError("live lead retrieval")

    monkeypatch.setattr("app.services.lead_forms.live_meta_lead_client", _live)
    settings = get_settings()
    monkeypatch.setattr(settings, "meta_lead_access_token", "lead-token")
    monkeypatch.setattr(settings, "meta_page_access_token", "posting-token")
    db = get_session()
    try:
        user, plan = _workspace(db)
        _bind(db, user, plan)
        accept_leadgen_notification(db, _notice("leadgen-prepared", ad=AD))
        assert process_due_lead_receipts(db, client=None) == 1
        prepared = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-prepared"))
        assert prepared is not None
        assert prepared.status == "received"
        assert prepared.error == PREPARED_BLOCK
        assert prepared.lead_id is None
        assert calls == []

        tenant = db.get(Tenant, user.tenant_id)
        assert tenant is not None
        tenant.operating_mode = "LIVE"
        _close_scopes(db, user.tenant_id)
        monkeypatch.setattr(settings, "meta_lead_access_token", "")
        accept_leadgen_notification(db, _notice("leadgen-posting-token", ad=AD))
        process_due_lead_receipts(db, client=None)
        posting = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-posting-token"))
        assert posting is not None
        assert posting.status == "needs_review"
        assert posting.error == POSTING_TOKEN_UNUSED
        assert calls == []
    finally:
        db.rollback()
        db.close()


def test_receipt_processing_sets_the_mapped_tenant_before_writing(client: TestClient, monkeypatch) -> None:
    _ = client
    seen: list = []

    def spy(db, tenant_id):
        seen.append(tenant_id)
        return set_tenant_context(db, tenant_id)

    monkeypatch.setattr("app.services.lead_forms.set_tenant_context", spy)
    db = get_session()
    try:
        user, plan = _workspace(db)
        _bind(db, user, plan)
        accept_leadgen_notification(db, _notice("leadgen-tenant-context", ad=AD))
        graph = _Client([_Response(200, _detail("leadgen-tenant-context", {"email": EMAIL, "full_name": "Fixture Person", "may_we_reply": "yes"}, ad=AD))])
        assert process_due_lead_receipts(db, client=graph) == 1
        assert user.tenant_id in seen
        receipt = db.scalar(select(LeadFormReceipt).where(LeadFormReceipt.provider_lead_id == "leadgen-tenant-context"))
        assert receipt is not None and receipt.tenant_id == user.tenant_id
    finally:
        db.rollback()
        db.close()
