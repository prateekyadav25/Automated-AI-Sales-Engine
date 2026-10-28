"""Discovery follow-through with fixture providers. No Apify, Gmail, or live model."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai.providers import CompletionResult
from app.db.session import get_session
from app.models.ai import AIApproval, AIRecommendation
from app.models.autonomy import AutonomousRunStep, AutopilotSettings
from app.models.crm import ICP, Account, Contact, Lead, LeadScore, Task
from app.models.execution import AuthorizationGrant
from app.models.identity import DomainEvent, User
from app.models.integrations import EmailMessage
from app.models.lifecycle import Product, Sequence, SequenceEnrollment, SequenceStep
from app.models.operating_plan import DemoScope, OperatingPlan
from app.providers.lead_discovery import DiscoveredLead, DiscoveryResult
from app.services.demo_guard import DEMO_DISCOVERY_BLOCK, DISCOVERY_OUTSIDE, PREPARED_BLOCK, seal_scope
from app.services.discovery import run_discovery, workflow_fields
from app.services.marketing import research_prospects
from app.services.orchestrator import process_pending_events, retry_entity, run_lead_intake


class _Down:
    def complete(self, *args, **kwargs) -> CompletionResult:
        _ = (args, kwargs)
        raise RuntimeError("fixture model failure")


class _FixtureDiscovery:
    def __init__(self, people: list[DiscoveredLead]) -> None:
        self.people = people
        self.calls = 0
        self.queries = []

    def health(self) -> dict:
        return {"provider": "fixture-discovery", "is_mock": True, "connected": False, "reason": "fixture"}

    def discover(self, query) -> DiscoveryResult:
        self.calls += 1
        self.queries.append(query)
        return DiscoveryResult(
            candidates=self.people,
            provider="fixture-discovery",
            is_mock=True,
            connected=False,
            reason="fixture profiles",
        )


class _Billable:
    def __init__(self) -> None:
        self.calls = 0

    def health(self) -> dict:
        return {"provider": "apify", "is_mock": False, "connected": True, "reason": "stub"}

    def discover(self, query) -> DiscoveryResult:
        self.calls += 1
        _ = query
        return DiscoveryResult(candidates=[], provider="apify", is_mock=False, connected=True)


def _user(db, email: str = "admin@agrayian.demo") -> User:
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


def _score(db, lead: Lead, *, emit: bool = True, correlation_id: str = "") -> LeadScore:
    _ = (emit, correlation_id)
    total = 10 if lead.company_name else 95
    row = LeadScore(
        tenant_id=lead.tenant_id,
        created_by=lead.created_by,
        lead_id=lead.id,
        total=total,
        reasons="fixture score",
        version="rules-v1",
    )
    db.add(row)
    db.flush()
    return row


def _person(first: str, last: str, *, email: str = "", company: str = "", title: str = "", ref: str) -> DiscoveredLead:
    return DiscoveredLead(
        first_name=first,
        last_name=last,
        email=email,
        title=title,
        company_name=company,
        linkedin_url=f"https://www.linkedin.com/in/{ref}",
        provider_ref=ref,
        source_url=f"https://www.linkedin.com/in/{ref}",
    )


def _close_scopes(db, tenant_id) -> None:
    rows = db.scalars(
        select(DemoScope).where(
            DemoScope.tenant_id == tenant_id,
            DemoScope.deleted_at.is_(None),
            DemoScope.status.in_(["prepared", "authorized"]),
        )
    ).all()
    for row in rows:
        row.status = "closed"


def test_follow_through_is_idempotent_and_permission_is_separate(client: TestClient, monkeypatch) -> None:
    _ = client
    monkeypatch.setattr("app.services.content.get_llm_provider", lambda *args, **kwargs: _Down())
    monkeypatch.setattr("app.services.orchestrator.score_lead", _score)
    user_holder: dict = {}
    sparse = _person("Sparse", "Lane", company="Sparse Freight", ref="sparse-lane")
    eligible = _person("Nora", "Vale", email="nora.vale@northwind.test", company="Northwind", title="CRO", ref="nora-vale")
    high = _person("High", "Score", email="high.score@mail.test", ref="high-score")
    twin_a = _person("Mina", "Rao", company="Harbor Example", ref="mina-rao-a")
    twin_b = _person("Mina", "Rao", company="Harbor Example", ref="mina-rao-b")
    opted = _person("Opted", "Out", email="opted.out@harbor.test", company="Harbor Example", ref="opted-out")
    fixture = _FixtureDiscovery([sparse, eligible, high, twin_a, twin_b, opted])
    monkeypatch.setattr("app.services.discovery.get_lead_discovery_provider", lambda *args, **kwargs: fixture)
    db = get_session()
    try:
        user = _user(db)
        other = _user(db, "admin@northline.demo")
        user_holder["id"] = user.id
        settings = db.scalar(select(AutopilotSettings).where(AutopilotSettings.tenant_id == user.tenant_id))
        assert settings is not None
        settings.enabled = True
        settings.enrichment_enabled = True
        settings.lead_scoring_enabled = True
        settings.qualification_enabled = True
        settings.research_enabled = True
        settings.sequence_enrollment_enabled = True
        settings.outreach_preparation_enabled = True
        settings.email_approval_required = True
        settings.quiet_hours_start = "00:00"
        settings.quiet_hours_end = "00:00"
        grants = db.scalars(
            select(AuthorizationGrant).where(
                AuthorizationGrant.tenant_id == user.tenant_id,
                AuthorizationGrant.deleted_at.is_(None),
                AuthorizationGrant.status == "active",
                AuthorizationGrant.mode == "bounded_autopilot",
            )
        ).all()
        for grant in grants:
            grant.status = "paused"
        db.add(
            Contact(
                tenant_id=user.tenant_id,
                created_by=user.id,
                first_name="Opted",
                last_name="Out",
                email="opted.out@harbor.test",
                opt_out=True,
            )
        )
        gov = Product(
            tenant_id=user.tenant_id,
            created_by=user.id,
            sku="GOV",
            name="One-time setup, under 200 employees",
            kind="one_time",
            list_price=Decimal("300000"),
            currency="INR",
            description="Autonomous Revenue OS for companies under 200 employees.",
        )
        other_product = Product(
            tenant_id=user.tenant_id,
            created_by=user.id,
            sku="CS",
            name="Success Desk",
            kind="one_time",
            list_price=Decimal("400000"),
            currency="INR",
            description="Success Desk for companies under 200 employees.",
        )
        db.add(gov)
        db.add(other_product)
        db.flush()
        gov_plan = OperatingPlan(
            tenant_id=user.tenant_id,
            created_by=user.id,
            product_id=gov.id,
            channel="linkedin",
            audience="software operators",
            status="running",
            context_snapshot=json.dumps(
                {
                    "customer_facing_name": "Autonomous Revenue OS",
                    "description": "Autonomous Revenue OS for companies under 200 employees.",
                    "kind": "one_time",
                    "list_price": "300000",
                    "currency": "INR",
                    "sku": "GOV",
                    "benefits": ["one operating cadence"],
                }
            ),
        )
        other_plan = OperatingPlan(
            tenant_id=user.tenant_id,
            created_by=user.id,
            product_id=other_product.id,
            channel="linkedin",
            audience="other buyers",
            status="running",
            context_snapshot=json.dumps({"customer_facing_name": "Success Desk", "list_price": "400000", "benefits": ["a different desk"]}),
        )
        db.add(gov_plan)
        db.add(other_plan)
        icp = ICP(
            tenant_id=user.tenant_id,
            created_by=user.id,
            name="Software operators",
            industries="software",
            personas="CRO",
            is_default=False,
        )
        db.add(icp)
        db.flush()
        sequence = Sequence(
            tenant_id=user.tenant_id,
            created_by=user.id,
            name=f"Bound cadence {uuid4().hex[:6]}",
            channel="email",
            status="live",
            routing_priority=1000,
            operating_plan_id=gov_plan.id,
        )
        db.add(sequence)
        db.flush()
        db.add(
            SequenceStep(
                tenant_id=user.tenant_id,
                created_by=user.id,
                sequence_id=sequence.id,
                position=1,
                action_type="email_draft",
                template="Hello {{first_name}}. Offer a 40% discount and a customer testimonial.",
            )
        )
        db.add(
            AIRecommendation(
                tenant_id=other.tenant_id,
                created_by=other.id,
                entity_type="account",
                entity_id=str(uuid4()),
                kind="research",
                title="Other tenant",
                body=json.dumps({"brief": "Northline private finding", "sources": ["https://northline.test/private"]}),
                status="draft",
            )
        )
        db.flush()
        first = run_discovery(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            search_query="software operators",
            provider=fixture,
            enforce_budget=False,
            operating_plan_id=gov_plan.id,
            icp_id=icp.id,
        )
        assert fixture.calls == 1
        assert "software" in fixture.queries[0].industries
        assert first["filters"]["operating_plan_id"] == str(gov_plan.id)
        assert first["filters"]["icp_id"] == str(icp.id)
        assert first["created"] == 5
        stored = db.scalars(select(Lead).where(Lead.tenant_id == user.tenant_id, Lead.provider_ref.in_(["sparse-lane", "nora-vale", "high-score", "mina-rao-a", "mina-rao-b"]))).all()
        assert len(stored) == 5
        assert all(row.operating_plan_id == gov_plan.id and row.icp_id == icp.id and row.consent_email is False for row in stored)
        assert db.scalar(select(Lead).where(Lead.tenant_id == user.tenant_id, Lead.email == "opted.out@harbor.test")) is None
        ours = [str(row.id) for row in stored]
        assert db.scalar(select(func.count()).select_from(AIApproval).where(AIApproval.entity_id.in_(ours), AIApproval.action_type == "sequence.email.send")) == 0
        by_ref = {row.provider_ref: row for row in stored}
        by_ref["nora-vale"].consent_email = True
        by_ref["high-score"].consent_email = True
        db.flush()
        process_pending_events(db, tenant_id=user.tenant_id, actor_id=user.id)
        sparse_lead = by_ref["sparse-lane"]
        eligible_lead = by_ref["nora-vale"]
        high_lead = by_ref["high-score"]
        db.flush()
        enrich = db.scalar(
            select(AutonomousRunStep).where(
                AutonomousRunStep.entity_id == str(sparse_lead.id),
                AutonomousRunStep.name == "enrich",
            )
        )
        assert enrich is not None and enrich.status == "incomplete"
        assert "email" in (enrich.detail_json or "")
        assert sparse_lead.email == ""
        assert sparse_lead.consent_email is False
        account = db.get(Account, sparse_lead.account_id) if sparse_lead.account_id else None
        assert account is None or account.website == ""
        sparse_task = db.scalar(select(Task).where(Task.entity_id == str(sparse_lead.id), Task.status == "open"))
        assert sparse_task is not None
        assert "consent" in sparse_task.title.lower()
        assert _count(db, AIApproval, user.tenant_id, sparse_lead.id, "email.acknowledge") == 0
        assert _count(db, AIApproval, user.tenant_id, sparse_lead.id, "sequence.email.send") == 0
        assert _count(db, AIApproval, user.tenant_id, high_lead.id, "sequence.email.send") == 0
        assert _count(db, AIApproval, user.tenant_id, high_lead.id, "email.acknowledge") == 0
        assert db.scalar(select(DomainEvent.id).where(DomainEvent.event_type == "lead.disqualified", DomainEvent.entity_id == str(high_lead.id))) is None
        send = db.scalars(
            select(AIApproval).where(
                AIApproval.tenant_id == user.tenant_id,
                AIApproval.entity_id == str(eligible_lead.id),
                AIApproval.action_type == "sequence.email.send",
                AIApproval.deleted_at.is_(None),
            )
        ).all()
        assert len(send) == 1
        payload = json.loads(send[0].payload_json)
        assert payload["product_name"] == "Autonomous Revenue OS"
        assert "Success Desk" not in payload["body"]
        assert "400,000" not in payload["body"]
        assert "40%" not in payload["body"]
        assert "testimonial" not in payload["body"].lower()
        assert "follow-up" not in payload["subject"].lower()
        assert "Northline private finding" not in payload["body"]
        assert _count(db, AIApproval, user.tenant_id, eligible_lead.id, "email.acknowledge") == 0
        enrollment = db.scalar(select(SequenceEnrollment).where(SequenceEnrollment.lead_id == eligible_lead.id))
        assert enrollment is not None and enrollment.sequence_id == sequence.id
        assert db.scalar(select(func.count()).select_from(EmailMessage).where(EmailMessage.lead_id == eligible_lead.id)) == 0
        original = payload["body"]
        db.add(
            AIRecommendation(
                tenant_id=user.tenant_id,
                created_by=user.id,
                entity_type="account",
                entity_id=str(eligible_lead.account_id),
                kind="research",
                title="Later research",
                body=json.dumps({"brief": "A newly obtained freight finding.", "sources": ["https://example.test/freight"]}),
                status="draft",
            )
        )
        db.flush()
        process_pending_events(db, tenant_id=user.tenant_id, actor_id=user.id)
        retry_entity(db, tenant_id=user.tenant_id, actor_id=user.id, entity_type="lead", entity_id=str(eligible_lead.id))
        again = db.scalars(
            select(AIApproval).where(
                AIApproval.tenant_id == user.tenant_id,
                AIApproval.entity_id == str(eligible_lead.id),
                AIApproval.action_type == "sequence.email.send",
                AIApproval.deleted_at.is_(None),
            )
        ).all()
        assert len(again) == 1
        reread = json.loads(again[0].payload_json)
        assert reread["body"] == original
        assert "freight finding" not in reread["body"]
        tasks_before = db.scalar(select(func.count()).select_from(Task).where(Task.entity_id == str(sparse_lead.id), Task.status == "open"))
        second = run_discovery(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            provider=fixture,
            enforce_budget=False,
            operating_plan_id=gov_plan.id,
            icp_id=icp.id,
        )
        process_pending_events(db, tenant_id=user.tenant_id, actor_id=user.id)
        assert second["created"] == 0
        assert fixture.calls == 2
        assert db.scalar(select(func.count()).select_from(Lead).where(Lead.tenant_id == user.tenant_id, Lead.provider_ref == "mina-rao-a")) == 1
        assert db.scalar(select(func.count()).select_from(Task).where(Task.entity_id == str(sparse_lead.id), Task.status == "open")) == tasks_before
        assert _count(db, AIApproval, user.tenant_id, eligible_lead.id, "sequence.email.send") == 1
    finally:
        db.rollback()
        db.close()


def test_ambiguous_plan_and_icp_do_not_guess(client: TestClient, monkeypatch) -> None:
    _ = client
    stub = _FixtureDiscovery([])
    monkeypatch.setattr("app.services.discovery.get_lead_discovery_provider", lambda *args, **kwargs: stub)
    db = get_session()
    try:
        user = _user(db)
        seed = db.scalar(select(ICP).where(ICP.tenant_id == user.tenant_id, ICP.is_default.is_(True)))
        if seed is not None:
            seed.is_default = False
        db.add(ICP(tenant_id=user.tenant_id, created_by=user.id, name="One profile", industries="software", is_default=False))
        db.add(ICP(tenant_id=user.tenant_id, created_by=user.id, name="Another profile", industries="healthcare", is_default=False))
        db.add(OperatingPlan(tenant_id=user.tenant_id, created_by=user.id, channel="linkedin", status="running", audience="one"))
        db.add(OperatingPlan(tenant_id=user.tenant_id, created_by=user.id, channel="linkedin", status="running", audience="two"))
        db.flush()
        refused = research_prospects(db, tenant_id=user.tenant_id, actor_id=user.id)
        assert refused["next_action"] == "choose_operating_plan"
        assert stub.calls == 0
        plans = db.scalars(select(OperatingPlan).where(OperatingPlan.tenant_id == user.tenant_id, OperatingPlan.status == "running")).all()
        for plan in plans:
            plan.status = "completed"
        db.flush()
        icp_refused = research_prospects(db, tenant_id=user.tenant_id, actor_id=user.id)
        assert icp_refused["next_action"] == "choose_icp"
        assert stub.calls == 0
    finally:
        db.rollback()
        db.close()


def test_demo_scopes_make_no_live_discovery_calls(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        user = _user(db)
        stub = _Billable()
        _close_scopes(db, user.tenant_id)
        missing = run_discovery(db, tenant_id=user.tenant_id, actor_id=user.id, provider=stub, enforce_budget=False, search_query="people")
        assert missing["reason"] == DEMO_DISCOVERY_BLOCK
        assert stub.calls == 0
        scope = DemoScope(tenant_id=user.tenant_id, created_by=user.id, status="prepared", allowed_actions=json.dumps({"discovery.search": 1}))
        db.add(scope)
        db.flush()
        prepared = run_discovery(db, tenant_id=user.tenant_id, actor_id=user.id, provider=stub, enforce_budget=False, search_query="people")
        assert prepared["reason"] == PREPARED_BLOCK
        assert scope.status == "prepared"
        assert stub.calls == 0
        scope.status = "authorized"
        scope.expires_at = datetime.now(UTC) - timedelta(days=1)
        scope.allowed_actions = json.dumps({"discovery.search": 1})
        seal_scope(scope)
        expired = run_discovery(db, tenant_id=user.tenant_id, actor_id=user.id, provider=stub, enforce_budget=False, search_query="people")
        assert "expired" in expired["reason"].lower()
        assert stub.calls == 0
        scope.expires_at = datetime.now(UTC) + timedelta(days=1)
        scope.allowed_actions = json.dumps({"email.send": 1})
        seal_scope(scope)
        wrong = run_discovery(db, tenant_id=user.tenant_id, actor_id=user.id, provider=stub, enforce_budget=False, search_query="people")
        assert wrong["reason"] == DISCOVERY_OUTSIDE
        assert stub.calls == 0
    finally:
        db.rollback()
        db.close()


def test_ineligible_discovery_follow_through_does_not_create_a_send_approval(client: TestClient, monkeypatch) -> None:
    """A browser check once showed an ineligible lead beside a send approval.

    That pair was inserted by hand so the page could render both fields, and it was deleted.
    Follow-through does not create a send approval for a discovered person without permission.
    """
    _ = client
    monkeypatch.setattr("app.services.content.get_llm_provider", lambda *args, **kwargs: _Down())
    monkeypatch.setattr("app.services.orchestrator.score_lead", _score)
    db = get_session()
    try:
        user = _user(db)
        lead = Lead(
            tenant_id=user.tenant_id,
            created_by=user.id,
            first_name="Display",
            last_name="Fixture",
            email="",
            company_name="Fixture Freight",
            source="ai_discovery",
            consent_email=False,
            notes="LinkedIn: https://www.linkedin.com/in/display-fixture",
        )
        db.add(lead)
        db.flush()
        run_lead_intake(db, tenant_id=user.tenant_id, actor_id=user.id, lead=lead, correlation_id="display-fixture")
        assert _count(db, AIApproval, user.tenant_id, lead.id, "sequence.email.send") == 0
        assert _count(db, AIApproval, user.tenant_id, lead.id, "email.acknowledge") == 0
        approval = AIApproval(
            tenant_id=user.tenant_id,
            created_by=user.id,
            action_level=1,
            action_type="sequence.email.send",
            title="Display only",
            entity_type="lead",
            entity_id=str(lead.id),
            status="pending",
            payload_json="{}",
            idempotency_key="fixture-review-do-not-send",
        )
        db.add(approval)
        db.flush()
        view = workflow_fields(db, lead)
        assert view["approval_id"] == str(approval.id)
        assert view["eligibility"] != "outbound_eligible"
        assert view["next_action"]
    finally:
        db.rollback()
        db.close()


def _count(db, model, tenant_id, lead_id, action: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.tenant_id == tenant_id,
                model.entity_id == str(lead_id),
                model.action_type == action,
                model.deleted_at.is_(None),
            )
        )
        or 0
    )
