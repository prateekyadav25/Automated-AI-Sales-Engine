"""Tracking links, enquiry attribution, and separate traffic, lead, and sales measurements."""

from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session
from app.models.assessment import AssessmentDecision
from app.models.crm import Opportunity
from app.models.growth import GrowthCalendarItem, GrowthLinkClick, GrowthTrackingLink
from app.models.lifecycle import DealPurchase, Quote
from app.services.acquisition import capture_inbound
from app.services.growth import accounts as account_service
from app.services.growth import brand as brand_service
from app.services.growth import creative as creative_service
from app.services.growth import planner
from app.services.growth.attribution import attribution_report, collect_ga4, resolve_redirect, traffic_summary
from app.services.growth.common import now
from tests.growth_support import FakeResponse, approved_brand, approved_strategy, form, user


class FakeGA4:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url: str, headers: dict, json: dict):
        self.calls.append({"url": url, "headers": headers, "json": json})
        day = (now() - timedelta(days=1)).strftime("%Y%m%d")
        return FakeResponse(
            200,
            {
                "metricHeaders": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"}],
                "rows": [
                    {"dimensionValues": [{"value": day}, {"value": "instagram"}, {"value": "social_organic"}, {"value": "social-growth-v1"}], "metricValues": [{"value": "14"}, {"value": "11"}, {"value": "2"}]},
                    {"dimensionValues": [{"value": day}, {"value": "google"}, {"value": "organic"}, {"value": "(organic)"}], "metricValues": [{"value": "40"}, {"value": "33"}]},
                ],
            },
        )

    def close(self) -> None:
        return None


def _payload(token: str, email: str, company: str = "Pune Foods") -> dict:
    return {
        "first_name": "Meera",
        "last_name": "Kulkarni",
        "email": email,
        "company_name": company,
        "request_note": "Need two refrigerated trucks a week to Mumbai.",
        "consent_email": True,
        "source": "social_post",
        "channel": "instagram",
        "utm_source": "instagram",
        "utm_medium": "social_organic",
        "utm_campaign": "social-growth-v1",
        "growth": token,
    }


def test_tracking_link_click_and_enquiry_attribution_stay_separate(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        facts = approved_brand(db, admin.tenant_id, admin)
        account = account_service.create_fixture_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform="instagram", name="IG")
        approved_strategy(db, admin.tenant_id, admin, facts, [account], form(db, admin.tenant_id, admin))
        planner.plan_rolling_calendar(db, tenant_id=admin.tenant_id, actor_id=admin.id)
        item = db.scalar(select(GrowthCalendarItem).where(GrowthCalendarItem.tenant_id == admin.tenant_id, GrowthCalendarItem.account_id == account.id, GrowthCalendarItem.format == "image"))
        view = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id)
        token = view["link_url"].rsplit("/", 1)[-1]
        link = db.scalar(select(GrowthTrackingLink).where(GrowthTrackingLink.tenant_id == admin.tenant_id, GrowthTrackingLink.token == token))
        assert link is not None and link.calendar_item_id == item.id and link.token_hash != token
        destination = resolve_redirect(db, token, referer="https://l.instagram.com/", user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)")
        query = parse_qs(urlsplit(destination).query)
        assert query["growth"] == [token] and query["utm_source"] == ["instagram"] and query["utm_medium"] == ["social_organic"]
        assert urlsplit(destination).path.startswith("/capture/")
        resolve_redirect(db, token, referer="", user_agent="facebookexternalhit/1.1")
        assert resolve_redirect(db, "not-a-real-token-123", referer="", user_agent="Mozilla/5.0") is None
        clicks = db.scalars(select(GrowthLinkClick).where(GrowthLinkClick.link_id == link.id)).all()
        assert sorted(row.is_bot for row in clicks) == [False, True]
        assert {row.referrer_host for row in clicks} == {"l.instagram.com", ""}
        capture, lead, _reviews = capture_inbound(db, tenant_id=admin.tenant_id, actor_id=admin.id, payload=_payload(token, "meera@punefoods.example"))
        assert capture.growth_link_id == link.id and lead.growth_link_id == link.id
        later, same_lead, _ = capture_inbound(db, tenant_id=admin.tenant_id, actor_id=admin.id, payload=_payload("unknown-token-0000", "meera@punefoods.example"))
        assert same_lead.id == lead.id and same_lead.growth_link_id == link.id and later.growth_link_id is None
        other = user(db, "admin@northline.demo")
        _foreign, foreign_lead, _ = capture_inbound(db, tenant_id=other.tenant_id, actor_id=other.id, payload=_payload(token, "someone@elsewhere.example", "Elsewhere"))
        assert foreign_lead.growth_link_id is None
        db.add(AssessmentDecision(tenant_id=admin.tenant_id, created_by=admin.id, lead_id=lead.id, sales_qualified=True, outbound_eligible=False, response_eligible=True))
        opportunity = Opportunity(tenant_id=admin.tenant_id, created_by=admin.id, account_id=lead.account_id, name="Pune Foods cold chain", stage="closed_won", amount=Decimal("1"))
        db.add(opportunity)
        db.flush()
        quote = Quote(tenant_id=admin.tenant_id, created_by=admin.id, opportunity_id=opportunity.id, status="accepted")
        db.add(quote)
        db.flush()
        db.add(DealPurchase(tenant_id=admin.tenant_id, opportunity_id=opportunity.id, quote_id=quote.id, account_id=lead.account_id, currency="INR", amount=Decimal("300000"), status="won", fixture=True))
        db.flush()
        report = attribution_report(db, admin.tenant_id, start=now() - timedelta(days=1), end=now() + timedelta(days=1))
        assert report["traffic"]["first_party_clicks"] == 1 and report["traffic"]["bot_clicks_excluded"] == 1
        assert report["enquiries"]["count"] == 1 and report["enquiries"]["leads"] == 1
        assert report["qualified_leads"]["count"] == 1
        assert report["sales"]["won_purchases"] == 1
        assert report["sales"]["amounts"] == {} and report["sales"]["fixture_amounts"] == {"INR": "300000.00"}
        assert report["traffic"]["ga4"]["status"] == "not_configured"
        foreign = attribution_report(db, other.tenant_id, start=now() - timedelta(days=1), end=now() + timedelta(days=1))
        assert foreign["traffic"]["first_party_clicks"] == 0 and foreign["enquiries"]["count"] == 0
    finally:
        db.rollback()
        db.close()


def test_ga4_rows_are_stored_as_returned_and_only_social_rows_are_reported(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        assert collect_ga4(db, tenant_id=admin.tenant_id, actor_id=admin.id)["status"] == "blocked"
        profile = brand_service.ensure_profile(db, admin.tenant_id, admin.id)
        profile.ga4_property_id = "123456789"
        db.flush()
        assert "GA4_MODE" in collect_ga4(db, tenant_id=admin.tenant_id, actor_id=admin.id)["detail"]
        fake = FakeGA4()
        result = collect_ga4(db, tenant_id=admin.tenant_id, actor_id=admin.id, client=fake, token="fixture-oauth", provenance="fixture", days=7)
        assert result["stored"] == 2
        assert fake.calls[0]["url"].endswith("/properties/123456789:runReport")
        assert {item["name"] for item in fake.calls[0]["json"]["dimensions"]} == {"date", "sessionSource", "sessionMedium", "sessionCampaignName"}
        summary = traffic_summary(db, admin.tenant_id, start=now() - timedelta(days=3), end=now() + timedelta(days=1))
        assert summary["status"] == "recorded" and len(summary["rows"]) == 1
        row = summary["rows"][0]
        assert row["source"] == "instagram" and row["sessions"] == 14 and row["key_events"] == 2
        assert summary["coverage_days"] == 1
    finally:
        db.rollback()
        db.close()


def test_public_redirect_route_refuses_unknown_tokens(client: TestClient) -> None:
    assert client.get("/api/v1/public/r/unknown-token-12345", follow_redirects=False).status_code == 404
    assert client.get("/api/v1/public/r/bad", follow_redirects=False).status_code == 404


def test_capture_schema_accepts_the_growth_token(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        capture, lead, _ = capture_inbound(db, tenant_id=admin.tenant_id, actor_id=admin.id, payload=_payload("", "nobody@punefoods.example"))
        assert capture.growth_link_id is None and lead.growth_link_id is None
        assert isinstance(lead.id, UUID)
    finally:
        db.rollback()
        db.close()
