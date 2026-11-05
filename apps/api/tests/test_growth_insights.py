"""Organic insights read-back and period reporting through a scripted Graph client.

Readings in these tests are labeled fixture. The live sections of the report
must not count them.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import get_session
from app.models.growth import GrowthMedia, GrowthMetricObservation
from app.providers.meta_growth import FACEBOOK_PAGE_METRICS, MetaGrowthClient
from app.services.demo_guard import DEMO_METRICS_BLOCK
from app.services.growth import accounts as account_service
from app.services.growth import insights
from app.services.growth.common import now
from tests.conftest import login
from tests.growth_support import FakeGraph, close_scopes, graph_error, live_account, ok, set_mode, user

PAGE = "1000000002"
IG = "17841400000000001"


def _client(fake: FakeGraph) -> MetaGrowthClient:
    return MetaGrowthClient(client=fake, access_token="fixture-page-token-0000", version="v26.0")


def _readings(db, tenant_id, external_id, metric):
    return list(db.scalars(select(GrowthMetricObservation).where(GrowthMetricObservation.tenant_id == tenant_id, GrowthMetricObservation.external_id == external_id, GrowthMetricObservation.metric == metric)).all())


def test_facebook_page_and_post_insights_keep_zero_missing_and_unsupported(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        account = live_account(db, admin.tenant_id, admin, "facebook", PAGE)
        media = GrowthMedia(tenant_id=admin.tenant_id, account_id=account.id, external_id=f"{PAGE}_1", origin="historical", posted_at=now() - timedelta(days=2), format="image", pillar_key="offer", provenance="live")
        db.add(media)
        db.flush()
        day_one = (datetime.now(UTC) - timedelta(days=2)).replace(hour=7, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S+0000")
        day_two = (datetime.now(UTC) - timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S+0000")
        fake = FakeGraph()
        fake.on(
            "GET",
            rf"^{PAGE}/insights$",
            [
                ok(
                    {
                        "data": [
                            {"name": "page_media_view", "period": "day", "values": [{"value": 120, "end_time": day_one}, {"value": 0, "end_time": day_two}]},
                            {"name": "page_post_engagements", "period": "day", "values": [{"value": 7, "end_time": day_one}]},
                        ]
                    }
                )
            ],
        )
        post_responses = {
            "post_media_view,post_total_media_view_unique,post_clicks": graph_error(100, "(#100) The value must be a valid insights metric"),
            "post_media_view": ok({"data": [{"name": "post_media_view", "period": "lifetime", "values": [{"value": 340}]}]}),
            "post_total_media_view_unique": ok({"data": [{"name": "post_total_media_view_unique", "period": "lifetime", "values": [{"value": 0}]}]}),
            "post_clicks": graph_error(100, "(#100) The value must be a valid insights metric"),
        }
        fake.on("GET", rf"^{PAGE}_1/insights$", lambda call: post_responses[call["params"]["metric"]])
        result = insights.collect_account_insights(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=account.id, client=_client(fake), provenance="fixture")
        assert result["status"] == "recorded" and result["http_calls"] == 1
        views = sorted(_readings(db, admin.tenant_id, PAGE, "page_media_view"), key=lambda row: row.period_key)
        assert [(row.value, row.status) for row in views] == [(120, "recorded"), (0, "zero")]
        assert views[0].api_version == "v26.0" and views[0].endpoint == f"{PAGE}/insights" and views[0].provenance == "fixture"
        missing = _readings(db, admin.tenant_id, PAGE, "page_views_total")
        assert len(missing) == 1 and missing[0].value is None and missing[0].status == "unavailable"
        assert set(FACEBOOK_PAGE_METRICS) <= {row.metric for row in db.scalars(select(GrowthMetricObservation).where(GrowthMetricObservation.tenant_id == admin.tenant_id, GrowthMetricObservation.external_id == PAGE)).all()}
        media_result = insights.collect_media_insights(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=account.id, client=_client(fake), provenance="fixture")
        assert media_result["http_calls"] == 4
        assert _readings(db, admin.tenant_id, f"{PAGE}_1", "post_media_view")[0].value == 340
        unique = _readings(db, admin.tenant_id, f"{PAGE}_1", "post_total_media_view_unique")[0]
        assert unique.value == 0 and unique.status == "zero"
        clicks = _readings(db, admin.tenant_id, f"{PAGE}_1", "post_clicks")[0]
        assert clicks.value is None and clicks.status == "unsupported" and "valid insights metric" in clicks.error
        report = insights.performance_report(db, admin.tenant_id, start=now() - timedelta(days=7), end=now() + timedelta(days=1), account_id=account.id)
        section = report["accounts"][0]
        assert section["evidence"] == "live"
        assert all(metric["value"] is None for metric in section["account_metrics"]["metrics"])
        assert section["media"]["posts"][0]["measured"] is False
    finally:
        db.rollback()
        db.close()


def test_instagram_daily_totals_replace_rather_than_add_and_auth_failure_keeps_values(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        account = live_account(db, admin.tenant_id, admin, "instagram", IG)
        account.provenance = "fixture"
        reel = GrowthMedia(tenant_id=admin.tenant_id, account_id=account.id, external_id="1790000000000005", origin="engine", posted_at=now() - timedelta(days=1), format="reel", media_product_type="REELS", pillar_key="proof", provenance="fixture")
        db.add(reel)
        db.flush()
        totals = {"value": 50}

        def account_insights(call):
            if call["params"].get("metric_type") == "total_value":
                return ok({"data": [{"name": "views", "total_value": {"value": totals["value"]}}, {"name": "reach", "total_value": {"value": 30}}, {"name": "accounts_engaged", "total_value": {"value": 0}}]})
            return ok({"data": [{"name": "follower_count", "period": "day", "values": [{"value": 410, "end_time": (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+0000")}]}]})

        fake = FakeGraph().on("GET", rf"^{IG}/insights$", account_insights)
        fake.on("GET", r"^1790000000000005/insights$", [ok({"data": [{"name": "views", "values": [{"value": 900}]}, {"name": "reach", "values": [{"value": 610}]}, {"name": "ig_reels_avg_watch_time", "values": [{"value": 4200}]}]})])
        first = insights.collect_account_insights(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=account.id, client=_client(fake), provenance="fixture", days=3)
        assert first["http_calls"] == 4
        views = _readings(db, admin.tenant_id, IG, "views")
        assert len(views) == 3 and {row.value for row in views} == {50}
        assert {row.status for row in _readings(db, admin.tenant_id, IG, "accounts_engaged")} == {"zero"}
        assert {row.status for row in _readings(db, admin.tenant_id, IG, "total_interactions")} == {"unavailable"}
        assert _readings(db, admin.tenant_id, IG, "follower_count")[0].value == 410
        insights.collect_media_insights(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=account.id, client=_client(fake), provenance="fixture")
        assert _readings(db, admin.tenant_id, "1790000000000005", "views")[0].value == 900
        assert _readings(db, admin.tenant_id, "1790000000000005", "saved")[0].status == "unavailable"
        totals["value"] = 65
        insights.collect_account_insights(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=account.id, client=_client(fake), provenance="fixture", days=3)
        views = _readings(db, admin.tenant_id, IG, "views")
        assert len(views) == 3 and {row.value for row in views} == {65}
        report = insights.performance_report(db, admin.tenant_id, start=now() - timedelta(days=7), end=now() + timedelta(days=1), account_id=account.id)
        section = report["accounts"][0]
        assert section["evidence"] == "fixture"
        metrics = {row["metric"]: row for row in section["account_metrics"]["metrics"]}
        assert metrics["views"]["value"] == 195 and metrics["views"]["aggregation"] == "sum of daily values"
        assert metrics["views"]["coverage_days"] == 3 and metrics["views"]["partial"] is True
        assert metrics["reach"]["value"] == 30.0 and "not added" in metrics["reach"]["aggregation"]
        assert metrics["follower_count"]["aggregation"] == "latest daily value"
        assert metrics["total_interactions"]["value"] is None
        post = section["media"]["posts"][0]
        assert post["metrics"]["views"] == 900 and post["metrics"]["saved"] is None
        refused = FakeGraph().on("GET", rf"^{IG}/insights$", [graph_error(190, "Error validating access token", status=400)])
        insights.collect_account_insights(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=account.id, client=_client(refused), provenance="fixture", days=1)
        views = _readings(db, admin.tenant_id, IG, "views")
        assert {row.value for row in views} == {65}
        assert any("access token" in row.error for row in views)
        db.refresh(account)
        assert account.status == "needs_reconnect"
        count = db.scalar(select(func.count()).select_from(GrowthMetricObservation).where(GrowthMetricObservation.tenant_id == admin.tenant_id, GrowthMetricObservation.external_id == IG, GrowthMetricObservation.metric == "views"))
        assert count == 3
    finally:
        db.rollback()
        db.close()


def test_live_reads_are_gated_and_fixture_accounts_are_never_read(client: TestClient, monkeypatch) -> None:
    _ = client

    def refuse(*_args, **_kwargs):
        raise AssertionError("A live Meta client was constructed")

    monkeypatch.setattr("app.services.growth.insights.live_client", refuse)
    monkeypatch.setattr("app.services.growth.accounts.live_client", refuse)
    db = get_session()
    try:
        admin = user(db)
        account = live_account(db, admin.tenant_id, admin, "instagram", IG)
        blocked = insights.collect_account_insights(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=account.id)
        assert "SOCIAL_GROWTH_INSIGHTS_MODE" in blocked["detail"]
        monkeypatch.setattr(get_settings(), "social_growth_insights_mode", "live")
        set_mode(db, admin.tenant_id, "DEMO")
        close_scopes(db, admin.tenant_id)
        assert insights.collect_media_insights(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=account.id)["detail"] == DEMO_METRICS_BLOCK
        assert account_service.verify_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=account.id)["detail"] == DEMO_METRICS_BLOCK
        fixture = account_service.create_fixture_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform="facebook", name="Test page")
        assert "Fixture" in insights.collect_account_insights(db, tenant_id=admin.tenant_id, actor_id=admin.id, account_id=fixture.id)["detail"]
    finally:
        db.rollback()
        db.close()


def test_reporting_ranges_are_validated(client: TestClient) -> None:
    headers = login(client)
    assert client.get("/api/v1/social-growth/performance?range=7d", headers=headers).status_code == 200
    assert client.get("/api/v1/social-growth/performance?range=90d", headers=headers).status_code == 200
    assert client.get("/api/v1/social-growth/performance?range=custom&start=2026-10-01&end=2026-10-20", headers=headers).status_code == 200
    assert client.get("/api/v1/social-growth/performance?range=custom&start=2026-10-20&end=2026-10-01", headers=headers).status_code == 422
    assert client.get("/api/v1/social-growth/performance?range=2w", headers=headers).status_code == 422
    assert client.get("/api/v1/social-growth/attribution?range=1d", headers=headers).status_code == 200
