"""Organic proposals, one mock publication, and fake LinkedIn statistics.

No live LinkedIn, Meta, generation vendor, or discovery provider is called.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.session import get_session
from app.models.assessment import AssessmentDecision
from app.models.content import SellerProfile
from app.models.crm import Account, Lead, Opportunity
from app.models.lifecycle import Campaign, MeetingRecord, Product
from app.models.operating_plan import CreativeVersion, DemoScope, OperatingPlan
from app.models.organic import ContentProposal, OrganicMetricObservation
from app.models.social import SocialPost
from app.services.content_calendar import attach_local_preview, promote_proposal, propose_calendar, solid_png
from app.services.demo_guard import PREPARED_BLOCK
from app.services.discovery import workflow_fields
from app.services.marketing import (
    _attributed_leads,
    _hash,
    authorize_version,
    publish_scheduled,
    revise_version,
    schedule_version,
)
from app.services.organic_metrics import (
    collect_due_organic_metrics,
    collect_linkedin_metrics,
    prepare_recommendation,
    sales_evidence,
)
from app.services.product_context import build_product_context
from app.services.public_forms import create_form_key
from tests.test_organic_acquisition import _close_plans, _close_scopes, _fake_social, _user

SHARE = "urn:li:share:fixture-post"
ORG = "urn:li:organization:fixture"


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
        self.urls: list[str] = []

    def get(self, url: str, headers: dict) -> _Response:
        self.calls += 1
        self.urls.append(url)
        assert headers["Linkedin-Version"]
        assert headers["Authorization"].startswith("Bearer ")
        return self.responses.pop(0)


def _stats(impressions: int | None, clicks: int | None, *, unique: bool = False) -> dict:
    totals: dict = {}
    if impressions is not None:
        totals["impressionCount"] = impressions
    if clicks is not None:
        totals["clickCount"] = clicks
    totals["likeCount"] = 1
    totals["commentCount"] = 0
    totals["shareCount"] = 0
    if unique:
        totals["uniqueImpressionsCount"] = 3
    return {"elements": [{"totalShareStatistics": totals, "timeRange": {}}]}


def test_content_reaches_mock_publication_and_fake_metrics(client: TestClient, monkeypatch) -> None:
    _ = client
    _fake_social(monkeypatch)
    db = get_session()
    try:
        user = _user(db)
        tenant_id = user.tenant_id
        _close_scopes(db, tenant_id)
        _close_plans(db, tenant_id)
        profile = db.scalar(select(SellerProfile).where(SellerProfile.tenant_id == tenant_id, SellerProfile.deleted_at.is_(None)))
        assert profile is not None
        profile.summary = "Northwind sells the Northwind Desk."
        other = Product(
            tenant_id=tenant_id,
            created_by=user.id,
            sku="OTHER",
            name="Other desk",
            kind="subscription",
            list_price=Decimal("999999"),
            currency="INR",
            description="A different product for companies under 200 employees.",
        )
        selected = Product(
            tenant_id=tenant_id,
            created_by=user.id,
            sku="DESK",
            name="One-time setup, under 200 employees",
            kind="one_time",
            list_price=Decimal("300000"),
            currency="INR",
            description="A desk for a company under 200 employees.",
        )
        db.add_all([other, selected])
        db.flush()
        plan = OperatingPlan(
            tenant_id=tenant_id,
            created_by=user.id,
            product_id=selected.id,
            channel="linkedin",
            audience="Operators",
            status="running",
            next_action="prepare_content",
            context_snapshot=json.dumps(
                {
                    "customer_facing_name": "One-time setup, under 200 employees",
                    "description": "A desk for a company under 200 employees.",
                    "sku": "DESK",
                    "kind": "one_time",
                    "currency": "INR",
                    "list_price": "300000",
                }
            ),
        )
        extra = OperatingPlan(
            tenant_id=tenant_id,
            created_by=user.id,
            product_id=other.id,
            channel="linkedin",
            audience="Someone else",
            status="running",
        )
        db.add_all([plan, extra])
        db.flush()
        blocked = propose_calendar(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            plan_id=None,
            objective="Explain the desk",
            audience="Operators",
            channels=["linkedin"],
            start_on="2026-11-02",
            end_on="2026-11-02",
            cadence_days=7,
            themes=["How the desk is used"],
            call_to_action="Ask for a walkthrough.",
        )
        assert blocked["next_action"] == "choose_operating_plan"
        extra.status = "completed"
        db.flush()
        created = propose_calendar(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            plan_id=plan.id,
            objective="Explain the desk",
            audience="Operators",
            channels=["linkedin", "instagram", "youtube"],
            start_on="2026-11-02",
            end_on="2026-11-09",
            cadence_days=7,
            themes=["How the desk is used"],
            call_to_action="Ask for a walkthrough.",
        )
        assert created["customer_facing_name"] == "Northwind Desk"
        assert "Autonomous Revenue OS" not in created["customer_facing_name"]
        assert "under 200 employees" in created["offer_label"]
        assert "300,000" in created["offer_label"]
        proposals = created["proposals"]
        assert len(proposals) == 4
        assert {row["channel"] for row in proposals} == {"linkedin", "instagram"}
        assert all("trending" not in row["body"].lower() and "300,000" not in row["body"] for row in proposals)
        assert all("999,999" not in row["body"] and "999999" not in row["body"] for row in proposals)
        assert all(row["missing_research"] for row in proposals)
        assert all(row["status"] == "proposed" for row in proposals)
        assert all("product-context-v1" in row["context_version"] for row in proposals)
        replay = propose_calendar(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            plan_id=plan.id,
            objective="Explain the desk",
            audience="Operators",
            channels=["linkedin", "instagram"],
            start_on="2026-11-02",
            end_on="2026-11-09",
            cadence_days=7,
            themes=["How the desk is used"],
            call_to_action="Ask for a walkthrough.",
        )
        assert len(replay["proposals"]) == 4
        linkedin = next(row for row in proposals if row["channel"] == "linkedin")
        image = next(row for row in proposals if row["channel"] == "instagram")
        tiny = attach_local_preview(db, tenant_id=tenant_id, actor_id=user.id, proposal_id=image["id"], data=solid_png(1, 1))
        assert tiny["asset_state"] == "invalid"
        assert tiny["asset_url"] == ""
        preview = attach_local_preview(db, tenant_id=tenant_id, actor_id=user.id, proposal_id=image["id"], data=solid_png(640, 640))
        assert preview["asset_state"] == "local_preview"
        assert preview["public_media_ready"] is False
        assert "/api/v1/public/media/" in preview["asset_url"]
        assert "Northwind Desk" in preview["body"]
        video = db.get(ContentProposal, UUID(linkedin["id"]))
        assert video is not None
        video.format = "video"
        refused = promote_proposal(db, tenant_id=tenant_id, actor_id=user.id, proposal_id=video.id)
        assert refused["status"] == "unsupported"
        assert "video" in refused["detail"].lower()
        video.format = "text"
        video.asset_state = "not_required"
        draft = promote_proposal(db, tenant_id=tenant_id, actor_id=user.id, proposal_id=video.id)
        again = promote_proposal(db, tenant_id=tenant_id, actor_id=user.id, proposal_id=video.id)
        assert again["version_id"] == draft["version_id"]
        version = db.get(CreativeVersion, UUID(draft["version_id"]))
        assert version is not None and version.status == "draft"
        waiting = publish_scheduled(db, tenant_id=tenant_id, actor_id=user.id, only_due=True)
        assert "No scheduled version" in waiting["detail"]
        authorize_version(db, tenant_id=tenant_id, actor_id=user.id, version_id=version.id)
        schedule_version(db, tenant_id=tenant_id, actor_id=user.id, version_id=version.id)
        assert version.scheduled_for is not None and version.scheduled_for > datetime.now(UTC)
        future = publish_scheduled(db, tenant_id=tenant_id, actor_id=user.id, only_due=True)
        assert version.status == "scheduled"
        assert "No scheduled version" in future["detail"]
        version.scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
        scope = DemoScope(
            tenant_id=tenant_id,
            created_by=user.id,
            plan_id=plan.id,
            version_id=version.id,
            channel="linkedin",
            status="prepared",
            expires_at=datetime.now(UTC) + timedelta(days=2),
            allowed_actions=json.dumps({"social.publish": 1}),
        )
        db.add(scope)
        db.flush()
        held = publish_scheduled(db, tenant_id=tenant_id, actor_id=user.id, only_due=True)
        assert PREPARED_BLOCK in held["detail"]
        assert version.social_post_id is None
        scope.status = "closed"
        create_form_key(db, tenant_id=tenant_id, actor_id=user.id, name="organic-fixture")
        db.flush()
        published = publish_scheduled(db, tenant_id=tenant_id, actor_id=user.id, only_due=True)
        assert "mock" in published["detail"].lower()
        assert version.status == "published"
        assert version.outcome == "mock"
        assert version.provider_ref == ""
        assert version.permalink == ""
        posts = db.scalars(select(SocialPost).where(SocialPost.tenant_id == tenant_id, SocialPost.id == version.social_post_id)).all()
        assert len(list(posts)) == 1
        db.flush()
        second = publish_scheduled(db, tenant_id=tenant_id, actor_id=user.id, only_due=True)
        assert "No scheduled version" in second["detail"]
        assert db.scalar(select(func.count()).select_from(SocialPost).where(SocialPost.id == version.social_post_id)) == 1
        edited = revise_version(db, tenant_id=tenant_id, actor_id=user.id, version_id=version.id, body=version.body + "\n\nEdited copy.")
        successor = db.get(CreativeVersion, UUID(edited["version_id"]))
        assert successor is not None and successor.status == "draft" and successor.version_number != version.version_number
        assert version.status == "published"
        calls = {"count": 0}

        def pending_post(*args, **kwargs):
            calls["count"] += 1
            row = SocialPost(
                tenant_id=tenant_id,
                created_by=user.id,
                channel="linkedin",
                body="pending",
                status="pending",
                is_mock=False,
                external_id="",
                permalink="",
            )
            db.add(row)
            db.flush()
            return row

        monkeypatch.setattr("app.services.marketing.publish_post", pending_post)
        successor.status = "authorized"
        successor.content_hash = version.content_hash
        successor.headline = version.headline
        successor.body = version.body
        successor.image_url = version.image_url
        successor.content_hash = _hash(successor.headline, successor.body, successor.image_url)
        successor.status = "scheduled"
        successor.scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
        db.flush()
        unknown = publish_scheduled(db, tenant_id=tenant_id, actor_id=user.id, only_due=True)
        assert calls["count"] == 1
        assert "unknown" in unknown["detail"].lower()
        assert successor.permalink == ""
        again_unknown = publish_scheduled(db, tenant_id=tenant_id, actor_id=user.id, only_due=True)
        assert calls["count"] == 1
        assert "unknown" in again_unknown["detail"].lower()

        context = build_product_context(db, tenant_id, plan=plan)
        lead = Lead(
            tenant_id=tenant_id,
            created_by=user.id,
            first_name="Ada",
            last_name="North",
            email="ada.north@example.test",
            source="public_form",
            operating_plan_id=plan.id,
            creative_version_id=version.id,
            consent_email=True,
        )
        account = Account(tenant_id=tenant_id, created_by=user.id, name="North Freight")
        db.add_all([lead, account])
        db.flush()
        lead.account_id = account.id
        decision = AssessmentDecision(
            tenant_id=tenant_id,
            created_by=user.id,
            lead_id=lead.id,
            sales_qualified=True,
            outbound_eligible=False,
            response_eligible=True,
        )
        meeting = MeetingRecord(
            tenant_id=tenant_id,
            created_by=user.id,
            title="Walkthrough",
            lead_id=lead.id,
            provider="human",
            provider_event_id="fixture-meeting",
        )
        campaign = Campaign(tenant_id=tenant_id, created_by=user.id, name="Desk", channel="linkedin")
        db.add_all([decision, meeting, campaign])
        db.flush()
        plan.campaign_id = campaign.id
        won = Opportunity(
            tenant_id=tenant_id,
            created_by=user.id,
            account_id=account.id,
            campaign_id=campaign.id,
            name="Desk win",
            stage="closed_won",
            amount=Decimal("300000"),
        )
        open_deal = Opportunity(
            tenant_id=tenant_id,
            created_by=user.id,
            account_id=account.id,
            name="Still open",
            stage="qualification",
            amount=Decimal("1"),
        )
        stranger = Lead(
            tenant_id=tenant_id,
            created_by=user.id,
            first_name="No",
            last_name="Link",
            email="nolink@example.test",
            source="manual",
        )
        db.add_all([won, open_deal, stranger])
        db.flush()
        attributed = _attributed_leads(db, tenant_id, plan)
        assert [row.id for row in attributed] == [lead.id]
        evidence = sales_evidence(db, tenant_id, plan, attributed)
        assert evidence["attributed_enquiries"] == 1
        assert evidence["qualified_leads"] == 1
        assert evidence["meetings"] == 1
        assert evidence["won_deals"] == 1
        assert "300000" in str(evidence["won_amount"])

        mock_read = collect_linkedin_metrics(db, tenant_id=tenant_id, actor_id=user.id, client=_Client([]), provenance="fixture")
        assert mock_read["http_calls"] == 0
        missing = db.scalar(
            select(OrganicMetricObservation).where(
                OrganicMetricObservation.creative_version_id == version.id,
                OrganicMetricObservation.metric_name == "impressions",
            )
        )
        assert missing is not None
        assert missing.status == "unavailable"
        assert missing.value_number is None
        assert missing.provenance == "mock"

        live_version = CreativeVersion(
            tenant_id=tenant_id,
            created_by=user.id,
            plan_id=plan.id,
            channel="linkedin",
            version_number=9,
            headline="Provider post",
            body="Provider post",
            content_hash="abc",
            status="published",
            provider_ref=SHARE,
            outcome="confirmed",
            publication_token="provider-token",
            context_json=json.dumps(context.as_dict()),
        )
        facebook = CreativeVersion(
            tenant_id=tenant_id,
            created_by=user.id,
            plan_id=plan.id,
            channel="facebook",
            version_number=1,
            headline="Page",
            body="Page",
            content_hash="def",
            status="published",
            provider_ref="page-post",
            outcome="confirmed",
            publication_token="facebook-token",
        )
        db.add_all([live_version, facebook])
        db.flush()
        fake = _Client([
            _Response(200, _stats(12, 0)),
            _Response(200, _stats(15, 0)),
            _Response(403, {}),
            _Response(429, {}),
        ])
        first = collect_linkedin_metrics(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            client=fake,
            token="fixture-token",
            organization_urn=ORG,
            provenance="fixture",
        )
        assert first["http_calls"] == 1
        assert "shares=List(" in fake.urls[0]
        assert "organizationalEntity=" in fake.urls[0]
        stored = _metric(db, live_version.id, "impressions")
        clicks = _metric(db, live_version.id, "clicks")
        unique = _metric(db, live_version.id, "unique_impressions")
        assert stored.value_number == 12 and stored.status == "recorded"
        assert clicks.value_number == 0 and clicks.status == "zero"
        assert unique.value_number is None and unique.status == "unavailable"
        assert stored.provider_post_id == SHARE
        assert stored.source == "linkedin.organizationalEntityShareStatistics"
        assert stored.provenance == "fixture"
        second_read = collect_linkedin_metrics(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            client=fake,
            token="fixture-token",
            organization_urn=ORG,
            provenance="fixture",
        )
        assert second_read["http_calls"] == 1
        db.refresh(stored)
        assert stored.value_number == 15
        assert db.scalar(
            select(func.count()).select_from(OrganicMetricObservation).where(
                OrganicMetricObservation.creative_version_id == live_version.id,
                OrganicMetricObservation.metric_name == "impressions",
            )
        ) == 1
        denied = collect_linkedin_metrics(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            client=fake,
            token="fixture-token",
            organization_urn=ORG,
            provenance="fixture",
        )
        assert denied["http_calls"] == 1
        db.refresh(stored)
        assert stored.value_number == 15 and stored.status == "recorded"
        assert "permission" in stored.error.lower()
        limited = collect_linkedin_metrics(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            client=fake,
            token="fixture-token",
            organization_urn=ORG,
            provenance="fixture",
        )
        assert limited["http_calls"] == 1
        db.refresh(stored)
        assert stored.value_number == 15
        assert "rate" in stored.error.lower()
        unsupported = _metric(db, facebook.id, "impressions")
        assert unsupported.status == "unsupported" and unsupported.value_number is None
        before = version.body
        brief = plan.content_brief_json
        budget = campaign.budget
        small = prepare_recommendation(db, tenant_id=tenant_id, actor_id=user.id, plan=plan)
        assert small["verdict"] == "insufficient_evidence"
        stored.value_number = 120
        stored.status = "recorded"
        db.flush()
        enough = prepare_recommendation(db, tenant_id=tenant_id, actor_id=user.id, plan=plan)
        assert enough["verdict"] == "proposal_only"
        assert version.body == before
        assert plan.content_brief_json == brief
        assert campaign.budget == budget
        view = workflow_fields(db, lead)
        assert view["product_name"] == "Northwind Desk"
        assert "under 200 employees" in view["offer_label"]
        other_user = _user(db, "admin@northline.demo")
        assert propose_calendar(
            db,
            tenant_id=other_user.tenant_id,
            actor_id=other_user.id,
            plan_id=plan.id,
            objective="Explain the desk",
            audience="Operators",
            channels=["linkedin"],
            start_on="2026-11-02",
            end_on="2026-11-02",
            cadence_days=7,
            themes=["How the desk is used"],
            call_to_action="Ask for a walkthrough.",
        )["status"] == "blocked"
    finally:
        db.rollback()
        db.close()


def test_prepared_scope_does_not_call_linkedin_metrics(client: TestClient, monkeypatch) -> None:
    _ = client

    def _refuse():
        raise AssertionError("The live LinkedIn metrics client was opened")

    monkeypatch.setattr("app.services.organic_metrics.live_linkedin_client", _refuse)
    db = get_session()
    try:
        user = _user(db)
        _close_plans(db, user.tenant_id)
        product = Product(
            tenant_id=user.tenant_id,
            created_by=user.id,
            sku="DESK2",
            name="Desk",
            kind="one_time",
            list_price=Decimal("1"),
            currency="INR",
            description="Desk.",
        )
        db.add(product)
        db.flush()
        plan = OperatingPlan(
            tenant_id=user.tenant_id,
            created_by=user.id,
            product_id=product.id,
            channel="linkedin",
            status="running",
        )
        db.add(plan)
        db.flush()
        version = CreativeVersion(
            tenant_id=user.tenant_id,
            created_by=user.id,
            plan_id=plan.id,
            channel="linkedin",
            version_number=1,
            headline="Due",
            body="Due",
            content_hash="hash",
            status="published",
            provider_ref=SHARE,
            outcome="confirmed",
            publication_token="due-token",
        )
        db.add(version)
        db.flush()
        scope = DemoScope(
            tenant_id=user.tenant_id,
            created_by=user.id,
            plan_id=plan.id,
            version_id=version.id,
            channel="linkedin",
            status="prepared",
            expires_at=datetime.now(UTC) + timedelta(days=2),
            allowed_actions=json.dumps({}),
        )
        db.add(scope)
        db.flush()
        blocked = collect_linkedin_metrics(db, tenant_id=user.tenant_id, actor_id=user.id, client=None)
        assert blocked["blocked"] == PREPARED_BLOCK
        assert blocked["http_calls"] == 0
        assert collect_due_organic_metrics(db) >= 0
    finally:
        db.rollback()
        db.close()


def _metric(db, version_id, name: str) -> OrganicMetricObservation:
    row = db.scalar(
        select(OrganicMetricObservation).where(
            OrganicMetricObservation.creative_version_id == version_id,
            OrganicMetricObservation.metric_name == name,
            OrganicMetricObservation.deleted_at.is_(None),
        )
    )
    assert row is not None
    return row
