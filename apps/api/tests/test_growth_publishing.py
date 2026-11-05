"""Multi-account publishing through a scripted Graph client.

No live Meta client is constructed. The tests prove the gates, the official
container and upload flows, idempotency, reconciliation of unknown results,
back-off on rate limits, and reconnection after an expired token.
"""

import json
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import get_session
from app.models.ai import AIApproval
from app.models.assessment import ExternalEffect
from app.models.growth import GrowthCalendarItem, GrowthMedia, GrowthPublication
from app.models.operating_plan import DemoScope
from app.providers.meta_growth import MetaGrowthClient
from app.services.demo_guard import DEMO_PUBLISH_BLOCK, PREPARED_BLOCK
from app.services.dispatcher import dispatch_approval
from app.services.growth import creative as creative_service
from app.services.growth import governance, planner, publisher
from app.services.growth.common import aware, now
from app.services.growth.video import VideoUnavailable, tools
from tests.growth_support import (
    FakeGraph,
    approved_brand,
    approved_strategy,
    close_scopes,
    enable_growth,
    form,
    graph_error,
    live_account,
    network_error,
    ok,
    set_mode,
    user,
)

IG = "17841400000000001"
PAGE = "1000000002"


def _ready(db, monkeypatch, *, platform: str = "instagram", fmt: str = "image", grant: bool = True, mode: str = "PILOT", count: int = 1):
    monkeypatch.setattr(get_settings(), "public_api_base_url", "https://media.northwind.example")
    admin = user(db)
    set_mode(db, admin.tenant_id, mode)
    close_scopes(db, admin.tenant_id)
    enable_growth(db, admin.tenant_id)
    facts = approved_brand(db, admin.tenant_id, admin)
    account = live_account(db, admin.tenant_id, admin, platform, IG if platform == "instagram" else PAGE, page_id="1000000001" if platform == "instagram" else "")
    approved_strategy(db, admin.tenant_id, admin, facts, [account], form(db, admin.tenant_id, admin), formats={platform: {fmt: 3}})
    planner.plan_rolling_calendar(db, tenant_id=admin.tenant_id, actor_id=admin.id)
    if grant:
        governance.create_grant(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform=platform, volume_cap=10, days=7)
    items = list(db.scalars(select(GrowthCalendarItem).where(GrowthCalendarItem.tenant_id == admin.tenant_id, GrowthCalendarItem.account_id == account.id).order_by(GrowthCalendarItem.planned_for)).all())[:count]
    for item in items:
        view = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id)
        assert view["quality_state"] == "passed", view["review_reasons"]
        if view["status"] != "approved":
            creative_service.review_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, creative_id=UUID(view["id"]), decision="approve", note="Checked against the site.")
        creative_service.schedule_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id)
        item.planned_for = now() - timedelta(minutes=1)
    db.flush()
    return admin, account, items


def _client(fake: FakeGraph) -> MetaGrowthClient:
    return MetaGrowthClient(client=fake, access_token="fixture-page-token-0000", app_secret="fixture-secret", version="v26.0")


def _instagram_routes(fake: FakeGraph, *, statuses: list | None = None, publish=None, captured: dict | None = None) -> FakeGraph:
    store = captured if captured is not None else {}

    def create(call):
        store["caption"] = call["data"].get("caption", store.get("caption", ""))
        store["creates"] = store.get("creates", 0) + 1
        return ok({"id": f"container-{store['creates']}"})

    fake.on("POST", rf"^{IG}/media$", create)
    fake.on("GET", r"^container-\d+$", statuses if statuses is not None else [ok({"status_code": "FINISHED"})])
    fake.on("GET", rf"^{IG}/content_publishing_limit$", [ok({"data": [{"quota_usage": 3, "config": {"quota_total": 100}}]})])
    fake.on("POST", rf"^{IG}/media_publish$", publish if publish is not None else [ok({"id": "1790000000000001"})])
    fake.on("GET", r"^1790000000000\d+$", [ok({"id": "1790000000000001", "permalink": "https://www.instagram.com/p/FixturePost/"})])
    fake.on("GET", rf"^{IG}/media$", lambda call: ok({"data": [{"id": "1790000000000009", "caption": store.get("caption", "")}]}))
    return fake


def test_demo_scopes_disabled_mode_and_the_flag_never_reach_meta(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch, mode="DEMO")
        item = items[0]
        fake = FakeGraph()
        scope = DemoScope(tenant_id=admin.tenant_id, created_by=admin.id, status="prepared", expires_at=now() + timedelta(days=1), allowed_actions=json.dumps({"social.publish": 1}))
        db.add(scope)
        db.flush()
        assert publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id, client=_client(fake))["detail"] == PREPARED_BLOCK
        scope.status = "closed"
        db.flush()
        assert publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id, client=_client(fake))["detail"] == DEMO_PUBLISH_BLOCK
        set_mode(db, admin.tenant_id, "PILOT")

        def refuse(*_args, **_kwargs):
            raise AssertionError("A live Meta client was constructed")

        monkeypatch.setattr("app.services.growth.publisher.live_client", refuse)
        disabled = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id)
        assert "Publishing is disabled" in disabled["detail"]
        assert publisher.publish_due(db, tenant_id=admin.tenant_id) == 0
        enable_growth(db, admin.tenant_id, False)
        assert "ENABLE_SOCIAL_GROWTH" in publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id, client=_client(fake))["detail"]
        assert fake.calls == []
        assert db.scalar(select(func.count()).select_from(GrowthPublication).where(GrowthPublication.tenant_id == admin.tenant_id)) == 0
    finally:
        db.rollback()
        db.close()


def test_instagram_image_publishes_once_and_keeps_provider_ids(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, account, items = _ready(db, monkeypatch)
        item = items[0]
        fake = _instagram_routes(FakeGraph())
        result = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert result["published"] is True, result
        publication = db.get(GrowthPublication, item.publication_id)
        assert publication.container_id == "container-1" and publication.external_id == "1790000000000001"
        assert publication.permalink == "https://www.instagram.com/p/FixturePost/"
        assert publication.provenance == "live" and publication.api_version == "v26.0"
        create_call = next(call for call in fake.calls if call["method"] == "POST" and call["path"].endswith("/media"))
        assert create_call["data"]["image_url"].startswith("https://media.northwind.example/api/v1/public/media/")
        assert create_call["data"]["appsecret_proof"] and create_call["data"]["access_token"] == "fixture-page-token-0000"
        media = db.scalar(select(GrowthMedia).where(GrowthMedia.tenant_id == admin.tenant_id, GrowthMedia.external_id == "1790000000000001"))
        assert media is not None and media.origin == "engine" and media.pillar_key == item.pillar_key and media.account_id == account.id
        effect = db.scalar(select(ExternalEffect).where(ExternalEffect.tenant_id == admin.tenant_id, ExternalEffect.effect_key == publication.effect_key))
        assert effect.outcome == "confirmed" and effect.provider_ref == "1790000000000001"
        again = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert again["published"] is False and "published" in again["detail"]
        assert fake.count("POST", r"/media_publish$") == 1 and fake.count("POST", rf"^{IG}/media$") == 1
    finally:
        db.rollback()
        db.close()


def test_unknown_publish_result_is_reconciled_without_a_second_post(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch)
        item = items[0]
        captured: dict = {}
        fake = _instagram_routes(FakeGraph(), statuses=[ok({"status_code": "FINISHED"}), ok({"status_code": "PUBLISHED"})], publish=[network_error()], captured=captured)
        first = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert first["published"] is False and "unknown" in first["detail"].lower()
        publication = db.get(GrowthPublication, item.publication_id)
        assert publication.status == "unknown" and publication.container_id == "container-1"
        assert publisher.due_items(db, admin.tenant_id) and item.status == "publishing"
        second = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert second["published"] is True, second
        assert publication.external_id == "1790000000000009"
        assert fake.count("POST", r"/media_publish$") == 1
        assert fake.count("POST", rf"^{IG}/media$") == 1
    finally:
        db.rollback()
        db.close()


def test_rate_limits_back_off_and_expired_tokens_need_reconnection(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, account, items = _ready(db, monkeypatch, count=3)
        limited = FakeGraph().on("POST", rf"^{IG}/media$", [graph_error(4, "Application request limit reached")])
        result = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=items[0].id, client=_client(limited))
        assert result["published"] is False and "RATE_LIMIT" in result["detail"]
        publication = db.get(GrowthPublication, items[0].publication_id)
        assert publication.status == "rate_limited" and aware(publication.next_attempt_at) > now()
        assert items[0].id not in {row.id for row in publisher.due_items(db, admin.tenant_id)}
        expired = FakeGraph().on("POST", rf"^{IG}/media$", [graph_error(190, "Error validating access token: Session has expired", status=400, subcode=463)])
        failed = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=items[1].id, client=_client(expired))
        assert failed["status"] == "failed"
        db.refresh(account)
        assert account.status == "needs_reconnect" and "expired" in account.last_error
        blocked = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=items[2].id, client=_client(FakeGraph()))
        assert "Reconnect" in blocked["detail"] or "refused" in blocked["detail"]
    finally:
        db.rollback()
        db.close()


def test_reel_waits_for_meta_processing_then_publishes(client: TestClient, monkeypatch) -> None:
    _ = client
    try:
        tools()
    except VideoUnavailable as exc:
        pytest.skip(f"FFmpeg is not installed here: {exc}")
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch, fmt="reel")
        item = items[0]
        fake = _instagram_routes(FakeGraph(), statuses=[ok({"status_code": "IN_PROGRESS"}), ok({"status_code": "FINISHED"})])
        first = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert first["published"] is False and "PROCESSING" in first["detail"]
        publication = db.get(GrowthPublication, item.publication_id)
        assert publication.status == "processing"
        create = next(call for call in fake.calls if call["path"].endswith("/media"))
        assert create["data"]["media_type"] == "REELS" and create["data"]["video_url"].startswith("https://")
        publication.next_attempt_at = now() - timedelta(seconds=1)
        effect = db.scalar(select(ExternalEffect).where(ExternalEffect.tenant_id == admin.tenant_id, ExternalEffect.effect_key == publication.effect_key))
        effect.detail = json.dumps({"attempts": 1})
        db.flush()
        second = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert second["published"] is True, second
        assert fake.count("POST", rf"^{IG}/media$") == 1
    finally:
        db.rollback()
        db.close()


def test_facebook_photo_publishes_with_bytes_and_permalink(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch, platform="facebook")
        fake = FakeGraph()
        fake.on("POST", rf"^{PAGE}/photos$", [ok({"id": "9001", "post_id": f"{PAGE}_555"})])
        fake.on("GET", rf"^{PAGE}_555$", [ok({"id": f"{PAGE}_555", "permalink_url": f"https://www.facebook.com/{PAGE}/posts/555"})])
        result = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=items[0].id, client=_client(fake))
        assert result["published"] is True and result["external_id"] == f"{PAGE}_555"
        photo = fake.calls[0]
        assert photo["files"]["source"][2] == "image/jpeg" and photo["files"]["source"][1][:3] == b"\xff\xd8\xff"
        assert photo["data"]["message"]
    finally:
        db.rollback()
        db.close()


def test_facebook_reel_uses_the_upload_host_and_waits_for_a_post_id(client: TestClient, monkeypatch) -> None:
    _ = client
    try:
        tools()
    except VideoUnavailable as exc:
        pytest.skip(f"FFmpeg is not installed here: {exc}")
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch, platform="facebook", fmt="reel")
        item = items[0]
        fake = FakeGraph()
        fake.on("POST", rf"^{PAGE}/video_reels$", [ok({"video_id": "880001", "upload_url": "https://rupload.facebook.com/video-upload/v26.0/880001"}), ok({"success": True})])
        fake.on("POST", r"^880001$", [ok({"success": True})])
        fake.on("GET", r"^880001$", [ok({"status": {"video_status": "processing"}}), ok({"status": {"video_status": "ready"}, "post_id": f"{PAGE}_777"})])
        fake.on("GET", rf"^{PAGE}_777$", [ok({"permalink_url": "https://www.facebook.com/reel/777"})])
        first = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert first["published"] is False and "PROCESSING" in first["detail"]
        upload = next(call for call in fake.calls if call["url"].startswith("https://rupload.facebook.com/video-upload/v26.0/880001"))
        assert upload["headers"]["Authorization"].startswith("OAuth ") and int(upload["headers"]["file_size"]) == len(upload["content"])
        publication = db.get(GrowthPublication, item.publication_id)
        publication.next_attempt_at = now() - timedelta(seconds=1)
        effect = db.scalar(select(ExternalEffect).where(ExternalEffect.tenant_id == admin.tenant_id, ExternalEffect.effect_key == publication.effect_key))
        effect.detail = json.dumps({"attempts": 1})
        db.flush()
        second = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert second["published"] is True and second["external_id"] == f"{PAGE}_777"
        assert fake.count("POST", rf"^{PAGE}/video_reels$") == 2
    finally:
        db.rollback()
        db.close()


def test_without_a_grant_only_an_inbox_approval_of_that_creative_publishes(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch, grant=False, count=2)
        item = items[0]
        fake = _instagram_routes(FakeGraph())
        waiting = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert "decision inbox" in waiting["detail"] and fake.calls == []
        approvals = db.scalars(select(AIApproval).where(AIApproval.tenant_id == admin.tenant_id, AIApproval.action_type == "social.growth_publish", AIApproval.entity_id == str(item.id))).all()
        assert len(approvals) == 1 and approvals[0].status == "pending"
        approvals[0].status = "approved"
        db.flush()
        assert publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id, client=_client(fake))["published"] is True
        other = items[1]
        request = db.scalar(select(AIApproval).where(AIApproval.tenant_id == admin.tenant_id, AIApproval.action_type == "social.growth_publish", AIApproval.entity_id == str(other.id)))
        request.status = "approved"
        db.flush()

        def refuse(*_args, **_kwargs):
            raise AssertionError("A live Meta client was constructed")

        monkeypatch.setattr("app.services.growth.publisher.live_client", refuse)
        message = dispatch_approval(db, tenant_id=admin.tenant_id, actor_id=admin.id, row=request)
        assert "Publishing is disabled" in message
        creative = creative_service.owned_creative(db, admin.tenant_id, other.creative_id)
        creative.caption = creative.caption + " Edited after approval."
        db.flush()
        changed = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=other.id, client=_client(fake))
        assert "changed after approval" in changed["detail"]
    finally:
        db.rollback()
        db.close()


def test_operator_can_clear_an_unknown_result_for_a_new_attempt(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch)
        item = items[0]
        fake = _instagram_routes(FakeGraph(), statuses=[ok({"status_code": "FINISHED"}), ok({"status_code": "IN_PROGRESS"}), ok({"status_code": "FINISHED"})], publish=[network_error(), ok({"id": "1790000000000002"})])
        fake.routes = [route for route in fake.routes if not route[1].pattern.endswith("/media$") or route[0] != "GET"]
        fake.on("GET", rf"^{IG}/media$", [ok({"data": []})])
        publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        publication = db.get(GrowthPublication, item.publication_id)
        assert publication.status == "unknown"
        still = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert still["published"] is False and fake.count("POST", r"/media_publish$") == 1
        resolved = publisher.resolve_unknown(db, tenant_id=admin.tenant_id, actor_id=admin.id, publication_id=publication.id, decision="not_published", note="Checked the profile grid; nothing posted.")
        assert resolved["status"] == "requested" and publication.epoch == 1
        retried = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=item.id, client=_client(fake))
        assert retried["published"] is True and fake.count("POST", r"/media_publish$") == 2
    finally:
        db.rollback()
        db.close()
