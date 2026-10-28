"""Paused Meta assembly and capture attribution, using a scripted client only.

The ids below are fixture ids. They are not evidence of a live Meta ad account.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.session import get_session
from app.models.acquisition import InboundCapture
from app.models.ai import AIApproval
from app.models.crm import Lead, Opportunity
from app.models.funnel import AdCreative, AdSet, PaidAd
from app.models.identity import Tenant, User
from app.models.integrations import EmailMessage, ProviderAction
from app.models.lifecycle import Campaign, Product, SequenceEnrollment
from app.models.operating_plan import CreativeVersion, DemoScope, OperatingPlan
from app.providers.ads import META_ADS_GRAPH, MetaAdsProvider, PreparedAdsProvider
from app.services.acquisition import capture_inbound
from app.services.ads import EXHAUSTED_DAILY, NO_SPEND, budget_block_reason, queue_campaign_launch
from app.services.ads_assembly import assemble_paused_meta, assembly_view
from app.services.autopilot_settings import get_or_create_settings
from app.services.demo_guard import EXPIRED_BLOCK, PREPARED_BLOCK, external_execution_block
from app.services.orchestrator import run_lead_intake
from app.services.public_forms import create_form_key
from tests.test_organic_acquisition import _close_scopes, _user


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"

    def json(self) -> dict:
        return self._payload


class Scripted:
    def __init__(self, posts: list[tuple[int, dict]]) -> None:
        self._posts = list(posts)
        self.calls: list[dict] = []

    def post(self, url: str, params=None, data=None, json=None) -> _Response:
        _ = (params, json)
        self.calls.append({"method": "POST", "url": url, "data": dict(data or {})})
        status_code, payload = self._posts.pop(0)
        return _Response(status_code, payload)

    def get(self, url: str, params=None) -> _Response:
        self.calls.append({"method": "GET", "url": url, "data": dict(params or {})})
        return _Response(200, {"min_daily_budget": 100})

    def delete(self, *args, **kwargs) -> _Response:
        _ = (args, kwargs)
        raise AssertionError("assembly deleted a provider object")

    def close(self) -> None:
        return None


def _posts(client: Scripted) -> list[dict]:
    return [call for call in client.calls if call["method"] == "POST"]


@pytest.fixture(autouse=True)
def _no_live_http(monkeypatch) -> None:
    def boom(*args, **kwargs):
        _ = (args, kwargs)
        raise AssertionError("a live Meta client was constructed")

    monkeypatch.setattr("app.providers.ads.httpx.Client", boom)
    monkeypatch.setattr("app.services.ads.execute_ads_spend", boom)


def _provider(posts: list[tuple[int, dict]]) -> tuple[MetaAdsProvider, Scripted]:
    client = Scripted(posts)
    return MetaAdsProvider(token="fixture-token", ad_account_id="fixture-account", client=client, sandbox=True), client


def _ok(object_id: str) -> tuple[int, dict]:
    return 200, {"id": object_id}


def _workspace(db, user: User):
    product = Product(
        tenant_id=user.tenant_id,
        created_by=user.id,
        sku="NDR",
        name="Northline Desk Router",
        kind="one_time",
        list_price=Decimal("125000"),
        currency="INR",
        description="Routing desk for operations teams.",
    )
    db.add(product)
    db.flush()
    _form, _token = create_form_key(db, tenant_id=user.tenant_id, actor_id=user.id, name="meta-capture")
    plan = OperatingPlan(
        tenant_id=user.tenant_id,
        created_by=user.id,
        product_id=product.id,
        form_key_id=_form.id,
        channel="facebook",
        audience="Operations leads",
        status="running",
    )
    db.add(plan)
    db.flush()
    version = CreativeVersion(
        tenant_id=user.tenant_id,
        created_by=user.id,
        plan_id=plan.id,
        channel="facebook",
        version_number=1,
        headline="See the desk router",
        body="A short note about the selected product.",
        content_hash="meta-fixture-hash",
        status="authorized",
    )
    db.add(version)
    db.flush()
    campaign = Campaign(
        tenant_id=user.tenant_id,
        created_by=user.id,
        name="Paused website campaign",
        channel="meta",
        status="draft",
        objective="traffic",
        budget=Decimal("500"),
        currency="INR",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 20),
        timezone="Asia/Kolkata",
        audience="Operations leads in India",
        geography="IN",
        placements="facebook_feed",
        headline="See the desk router",
        body="A short note about the selected product.",
        call_to_action="LEARN_MORE",
        asset_ref="http://localhost/preview.jpg",
        destination="website_form",
        operating_plan_id=plan.id,
        creative_version_id=version.id,
    )
    db.add(campaign)
    db.flush()
    return product, plan, version, campaign


def _prepare(db, user: User) -> None:
    _close_scopes(db, user.tenant_id)
    db.add(
        DemoScope(
            tenant_id=user.tenant_id,
            created_by=user.id,
            status="prepared",
            expires_at=datetime.now(UTC) + timedelta(days=2),
            allowed_actions="{}",
        )
    )
    db.flush()


def test_paused_meta_assembly_and_attributed_enquiry(client) -> None:
    _ = client
    db = get_session()
    try:
        user = _user(db)
        _prepare(db, user)
        _product, plan, version, campaign = _workspace(db, user)
        provider, scripted = _provider([_ok("camp-1"), _ok("set-1"), _ok("creative-1"), _ok("ad-1")])
        provider.activate_campaign = lambda **kwargs: (_ for _ in ()).throw(AssertionError("activate"))  # type: ignore[method-assign]
        result = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert result["assembly_status"] == "paused"
        assert result["activated"] is False
        assert campaign.status == "paused"
        assert campaign.provider_status == "PAUSED"
        assert campaign.spent == 0
        assert campaign.external_campaign_id == "camp-1"
        ad_set = db.scalar(select(AdSet).where(AdSet.campaign_id == campaign.id))
        creative = db.scalar(select(AdCreative).where(AdCreative.campaign_id == campaign.id))
        paid = db.scalar(select(PaidAd).where(PaidAd.campaign_id == campaign.id))
        assert ad_set is not None and ad_set.external_id == "set-1" and ad_set.status == "paused"
        assert creative is not None and creative.external_id == "creative-1" and creative.ad_set_id == ad_set.id
        assert paid is not None and paid.external_id == "ad-1" and paid.status == "paused" and paid.ad_set_id == ad_set.id
        posts = _posts(scripted)
        assert [call["url"] for call in posts] == [
            f"{META_ADS_GRAPH}/act_fixture-account/campaigns",
            f"{META_ADS_GRAPH}/act_fixture-account/adsets",
            f"{META_ADS_GRAPH}/act_fixture-account/adcreatives",
            f"{META_ADS_GRAPH}/act_fixture-account/ads",
        ]
        assert posts[0]["data"]["status"] == "PAUSED"
        assert posts[0]["data"]["objective"] == "OUTCOME_TRAFFIC"
        assert "daily_budget" not in posts[0]["data"]
        assert posts[1]["data"]["status"] == "PAUSED"
        assert posts[1]["data"]["campaign_id"] == "camp-1"
        assert posts[1]["data"]["destination_type"] == "WEBSITE"
        assert posts[1]["data"]["optimization_goal"] == "LINK_CLICKS"
        assert "facebook_feed" not in posts[1]["data"]["targeting"] or "facebook" in posts[1]["data"]["targeting"]
        assert posts[2]["data"]["object_story_spec"]
        assert paid.tracking_token in posts[2]["data"]["object_story_spec"]
        assert "LEARN_MORE" in posts[2]["data"]["object_story_spec"]
        assert posts[3]["data"]["status"] == "PAUSED"
        assert posts[3]["data"]["adset_id"] == "set-1"
        assert "creative-1" in posts[3]["data"]["creative"]
        assert all(call["data"].get("status") != "ACTIVE" for call in posts)
        assert "Northline Desk Router" in campaign.context_json
        assert '"sku": "NDR"' in campaign.context_json
        view = assembly_view(db, campaign, include_enquiries=False)
        assert view["live_execution_ready"] is False
        assert "local" in view["live_execution_note"].lower()
        before = len(posts)
        again = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert again["assembly_status"] == "paused"
        assert len(_posts(scripted)) == before
        settings = get_or_create_settings(db, tenant_id=user.tenant_id, actor_id=user.id)
        settings.enabled = True
        with pytest.raises(HTTPException) as launch_error:
            queue_campaign_launch(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign)
        assert launch_error.value.status_code == 409
        assert campaign.status != "launched"
        payload = {
            "first_name": "Asha",
            "last_name": "Menon",
            "email": "asha.meta@example.com",
            "company_name": "Desk Co",
            "request_note": "We want the desk router for our team.",
            "consent_email": True,
            "source": "public_form",
            "channel": "website",
            "ad": paid.tracking_token,
            "campaign_id": str(uuid4()),
            "ad_id": "forged-from-browser",
        }
        _capture, lead, _reviews = capture_inbound(db, tenant_id=user.tenant_id, actor_id=user.id, payload=payload)
        assert lead is not None
        assert lead.campaign_id == campaign.id
        assert lead.ad_id == "ad-1"
        assert lead.operating_plan_id == plan.id
        assert lead.creative_version_id == version.id
        intake = run_lead_intake(db, tenant_id=user.tenant_id, actor_id=user.id, lead=lead)
        assert (intake.get("acknowledgement") or {}).get("status") in {"waiting_for_authorization", "waiting_for_configuration", "waiting_for_approval"}
        approval = db.scalar(
            select(AIApproval).where(
                AIApproval.tenant_id == user.tenant_id,
                AIApproval.entity_id == str(lead.id),
                AIApproval.action_type == "email.acknowledge",
            )
        )
        assert approval is not None
        assert "Northline Desk Router" in (approval.payload_json or "")
        assert "300,000" not in (approval.payload_json or "")
        sent = db.scalar(select(func.count()).select_from(EmailMessage).where(EmailMessage.lead_id == lead.id, EmailMessage.direction == "outbound"))
        assert sent == 0
        opportunities = db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.campaign_id == campaign.id))
        assert opportunities == 0
        enrolled = db.scalar(select(func.count()).select_from(SequenceEnrollment).where(SequenceEnrollment.lead_id == lead.id))
        assert enrolled == 0
        capture_inbound(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            payload={**payload, "ad_id": "second-forged", "request_note": "Following up on the same router."},
        )
        same = db.scalar(select(func.count()).select_from(Lead).where(Lead.email == "asha.meta@example.com", Lead.deleted_at.is_(None)))
        assert same == 1
        assert lead.ad_id == "ad-1"
        captures = db.scalar(
            select(func.count()).select_from(InboundCapture).where(InboundCapture.email == "asha.meta@example.com", InboundCapture.deleted_at.is_(None))
        )
        assert captures == 2
        later_payload = {**payload, "email": "later.meta@example.com", "first_name": "Dev", "request_note": "A separate enquiry about the desk router."}
        _later_capture, later, _later_reviews = capture_inbound(db, tenant_id=user.tenant_id, actor_id=user.id, payload=later_payload)
        assert later is not None and later.id != lead.id
        assert later.campaign_id == campaign.id
        assert later.ad_id == "ad-1"
        run_lead_intake(db, tenant_id=user.tenant_id, actor_id=user.id, lead=later)
        later_approval = db.scalar(
            select(AIApproval).where(
                AIApproval.entity_id == str(later.id),
                AIApproval.action_type == "email.acknowledge",
            )
        )
        assert later_approval is not None
        assert "Northline Desk Router" in (later_approval.payload_json or "")
        other = Tenant(name="Other ads workspace", slug=f"ads-{uuid4().hex[:8]}", operating_mode="DEMO")
        db.add(other)
        db.flush()
        foreign = PaidAd(
            tenant_id=other.id,
            campaign_id=campaign.id,
            tracking_token="foreign-token",
            status="paused",
            external_id="foreign-ad",
        )
        db.add(foreign)
        db.flush()
        _foreign_capture, foreign_lead, _foreign_reviews = capture_inbound(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            payload={**payload, "email": "forged.meta@example.com", "ad": "foreign-token", "campaign_id": str(campaign.id), "ad_id": "999"},
        )
        assert foreign_lead is not None
        assert foreign_lead.campaign_id is None
        assert foreign_lead.ad_id == ""
        actions = db.scalars(select(ProviderAction).where(ProviderAction.entity_id == str(campaign.id))).all()
        assert actions
        assert all(action.action_type == "ads.assemble" for action in actions)
        assert all(action.status == "CONFIRMED" for action in actions)
    finally:
        db.rollback()
        db.close()


def test_required_and_unsupported_objectives_do_not_call_meta(client) -> None:
    _ = client
    db = get_session()
    try:
        user = _user(db)
        _product, _plan, _version, campaign = _workspace(db, user)
        provider, scripted = _provider([_ok("should-not")])
        campaign.audience = ""
        with pytest.raises(HTTPException) as missing:
            assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert missing.value.status_code == 422
        assert _posts(scripted) == []
        campaign.audience = "Operations leads in India"
        campaign.objective = "awareness"
        blocked = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert blocked["assembly_status"] == "unsupported"
        campaign.objective = "traffic"
        campaign.destination = "native_form"
        native = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert native["assembly_status"] == "unsupported"
        assert "native" in native["blocker"].lower()
        campaign.destination = "website_form"
        campaign.channel = "linkedin"
        linkedin = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert linkedin["assembly_status"] == "unsupported"
        assert "LinkedIn" in linkedin["blocker"]
        assert _posts(scripted) == []
        user_tenant = db.get(Tenant, user.tenant_id)
        assert user_tenant is not None
        user_tenant.operating_mode = "LIVE"
        _close_scopes(db, user.tenant_id)
        campaign.channel = "meta"
        prepared = assemble_paused_meta(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            campaign=campaign,
            provider=PreparedAdsProvider("google"),
        )
        assert prepared["assembly_status"] == "unsupported"
        assert prepared["activated"] is False
        assert "completed" in prepared["blocker"].lower() or "cannot" in prepared["blocker"].lower()
        assert _posts(scripted) == []
    finally:
        db.rollback()
        db.close()


def test_partial_failure_is_replayed_without_rebuilding_the_campaign(client) -> None:
    _ = client
    db = get_session()
    try:
        user = _user(db)
        _product, _plan, _version, campaign = _workspace(db, user)
        provider, scripted = _provider([_ok("camp-keep"), (400, {"error": {"message": "ad set refused"}}), _ok("set-replay"), _ok("creative-replay"), _ok("ad-replay")])
        first = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert first["assembly_status"] == "partial"
        assert campaign.external_campaign_id == "camp-keep"
        assert "ad set" in first["blocker"].lower()
        assert db.scalar(select(AdSet).where(AdSet.campaign_id == campaign.id, AdSet.external_id != "")) is None
        second = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert second["assembly_status"] == "paused"
        campaign_posts = [call for call in _posts(scripted) if call["url"].endswith("/campaigns")]
        assert len(campaign_posts) == 1
        assert campaign.external_campaign_id == "camp-keep"
        assert campaign.spent == 0
        assert campaign.status == "paused"
    finally:
        db.rollback()
        db.close()


def test_unknown_create_is_not_repeated(client) -> None:
    _ = client
    db = get_session()
    try:
        user = _user(db)
        _product, _plan, _version, campaign = _workspace(db, user)
        provider, scripted = _provider([(200, {})])
        first = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert first["assembly_status"] == "unresolved"
        assert campaign.external_campaign_id == ""
        assert len(_posts(scripted)) == 1
        second = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=provider)
        assert second["assembly_status"] == "unresolved"
        assert len(_posts(scripted)) == 1
        assert "not repeated" in second["blocker"].lower()
    finally:
        db.rollback()
        db.close()


def test_prepared_and_expired_scopes_do_not_release_ads(client) -> None:
    _ = client
    db = get_session()
    try:
        user = _user(db)
        _product, _plan, _version, campaign = _workspace(db, user)
        _prepare(db, user)
        prepared = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=None)
        assert prepared["blocker"] == PREPARED_BLOCK
        assert prepared["assembly_status"] == "blocked"
        assert campaign.external_campaign_id == ""
        scope = db.scalar(select(DemoScope).where(DemoScope.tenant_id == user.tenant_id, DemoScope.status == "prepared"))
        assert scope is not None
        scope.status = "expired"
        db.flush()
        expired = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=None)
        assert expired["blocker"] == EXPIRED_BLOCK
        assert external_execution_block(db, tenant_id=user.tenant_id, action="ads.launch") == EXPIRED_BLOCK
        assert external_execution_block(db, tenant_id=user.tenant_id, action="email.acknowledge") == EXPIRED_BLOCK
        scope.status = "authorized"
        scope.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.flush()
        dated = assemble_paused_meta(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=campaign, provider=None)
        assert dated["blocker"] == EXPIRED_BLOCK
        assert external_execution_block(db, tenant_id=user.tenant_id, action="social.publish", real_effect=True) == EXPIRED_BLOCK
    finally:
        db.rollback()
        db.close()


def test_spend_limits_still_refuse_activation() -> None:
    class Settings:
        tenant_id = uuid4()
        daily_budget_limit = None
        monthly_budget_limit = 100

    class CampaignRow:
        budget = Decimal("500")

    assert budget_block_reason(None, settings=Settings(), campaign=CampaignRow()) == NO_SPEND  # type: ignore[arg-type]
    Settings.daily_budget_limit = "nope"
    assert budget_block_reason(None, settings=Settings(), campaign=CampaignRow()) == NO_SPEND  # type: ignore[arg-type]
    Settings.daily_budget_limit = 0
    Settings.monthly_budget_limit = 0
    assert budget_block_reason(None, settings=Settings(), campaign=CampaignRow()) == NO_SPEND  # type: ignore[arg-type]


def test_exhausted_limit_still_refuses_activation(client) -> None:
    _ = client
    db = get_session()
    try:
        user = _user(db)
        settings = get_or_create_settings(db, tenant_id=user.tenant_id, actor_id=user.id)
        settings.daily_budget_limit = Decimal("100")
        settings.monthly_budget_limit = Decimal("100")
        spent = Campaign(
            tenant_id=user.tenant_id,
            created_by=user.id,
            name="Already recorded",
            channel="linkedin",
            budget=Decimal("10"),
            spent=Decimal("100"),
            last_synced_at=datetime.now(UTC),
        )
        proposed = Campaign(
            tenant_id=user.tenant_id,
            created_by=user.id,
            name="Positive proposal",
            channel="linkedin",
            budget=Decimal("500"),
        )
        db.add_all([spent, proposed])
        db.flush()
        assert budget_block_reason(db, settings=settings, campaign=proposed) == EXHAUSTED_DAILY
        with pytest.raises(HTTPException) as blocked:
            queue_campaign_launch(db, tenant_id=user.tenant_id, actor_id=user.id, campaign=proposed)
        assert blocked.value.status_code == 409
    finally:
        db.rollback()
        db.close()
