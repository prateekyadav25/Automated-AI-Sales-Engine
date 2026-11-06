"""Controlled publication cases. The Graph client is scripted, so none of these are live-verified.

A one-post test must not turn SOCIAL_GROWTH_PUBLISH_MODE on. The scheduler
still no-ops while that mode is disabled.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import redact_text
from app.db.session import get_session
from app.models.growth import GrowthPublication
from app.models.identity import AuditLog
from app.providers.meta_growth import MetaGrowthClient
from app.services.growth import publisher
from app.services.growth.acceptance import deployment_preflight, overview
from app.services.growth.accounts import account_out, connect_account
from app.services.growth.video import VideoUnavailable, tools
from tests.growth_support import FakeGraph, ok, user
from tests.test_growth_publishing import IG, PAGE, _client, _instagram_routes, _ready


def _step(rows: list[dict], key: str) -> dict:
    return next(row for row in rows if row["step_key"] == key)


def _mode() -> str:
    return (get_settings().social_growth_publish_mode or "disabled").strip().lower()


def test_query_secrets_and_graph_errors_are_redacted() -> None:
    leaked = "https://graph.facebook.com/v26.0/me?access_token=EAABsecretvalue&appsecret_proof=proofvalue"
    cleaned = redact_text(leaked)
    assert "EAABsecretvalue" not in cleaned
    assert "proofvalue" not in cleaned
    assert "access_token=[REDACTED]" in cleaned

    class Response:
        status_code = 400
        content = b"{}"
        headers: dict = {}

        def json(self) -> dict:
            return {"error": {"message": "Invalid access_token=EAABsecretvalue", "code": 190}}

    class Client:
        def get(self, url: str, params: dict | None = None) -> Response:
            _ = url, params
            return Response()

        def close(self) -> None:
            return None

    result = MetaGrowthClient(client=Client(), access_token="EAABsecretvalue", app_secret="secret").get("me")
    assert result.ok is False
    assert "EAABsecretvalue" not in result.error_message


def test_preflight_stays_blocked_without_https_or_a_meta_app() -> None:
    report = deployment_preflight()
    assert report["status"] == "blocked"
    assert report["publish_mode"] == "disabled"
    assert report["ads_mode"] in {"disabled", "mock"}
    assert any("BLOCKED BY CONFIGURATION" in item for item in report["blockers"])
    assert "EAA" not in json.dumps(report)


def test_connecting_an_account_does_not_store_the_token_in_the_audit_or_the_api(client: TestClient) -> None:
    _ = client
    db = get_session()
    token = "EAABlive-token-value-should-not-leak"
    try:
        admin = user(db)
        account = connect_account(
            db,
            tenant_id=admin.tenant_id,
            actor_id=admin.id,
            platform="facebook",
            external_id="100000000000009",
            access_token=token,
            name="Northwind Page",
        )
        payload = json.dumps(account_out(account))
        assert token not in payload
        db.flush()
        audits = db.scalars(select(AuditLog).where(AuditLog.tenant_id == admin.tenant_id, AuditLog.entity_id == str(account.id))).all()
        assert audits
        for row in audits:
            assert token not in f"{row.before_json or ''}{row.after_json or ''}"
    finally:
        db.rollback()
        db.close()


def test_one_scripted_facebook_image_is_not_live_and_does_not_enable_publishing(client: TestClient, monkeypatch) -> None:
    _ = client
    before = _mode()
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch, platform="facebook")
        fake = FakeGraph()
        fake.on("POST", rf"^{PAGE}/photos$", [ok({"id": "9001", "post_id": f"{PAGE}_555"})])
        fake.on("GET", rf"^{PAGE}_555$", [ok({"id": f"{PAGE}_555", "permalink_url": f"https://www.facebook.com/{PAGE}/posts/555"})])
        result = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=items[0].id, client=_client(fake))
        assert result["published"] is True and result["external_id"] == f"{PAGE}_555"
        publication = db.get(GrowthPublication, items[0].publication_id)
        assert publication is not None and publication.provenance == "live"
        assert _step(overview(db, admin.tenant_id), "facebook_post")["status"] != "verified_live"
        assert publisher.publish_due(db, tenant_id=admin.tenant_id) == 0
        assert _mode() == before
    finally:
        db.rollback()
        db.close()


def test_one_scripted_instagram_image_is_not_live_and_does_not_enable_publishing(client: TestClient, monkeypatch) -> None:
    _ = client
    before = _mode()
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch)
        fake = _instagram_routes(FakeGraph())
        result = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=items[0].id, client=_client(fake))
        assert result["published"] is True
        assert result["external_id"] == "1790000000000001"
        assert _step(overview(db, admin.tenant_id), "instagram_image")["status"] != "verified_live"
        assert publisher.publish_due(db, tenant_id=admin.tenant_id) == 0
        assert fake.count("POST", rf"^{IG}/media_publish$") == 1
        assert _mode() == before
    finally:
        db.rollback()
        db.close()


def test_one_scripted_instagram_reel_is_not_live_and_does_not_enable_publishing(client: TestClient, monkeypatch) -> None:
    _ = client
    try:
        tools()
    except VideoUnavailable as exc:
        pytest.skip(f"FFmpeg is not installed here: {exc}")
    before = _mode()
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch, fmt="reel")
        fake = _instagram_routes(FakeGraph(), statuses=[ok({"status_code": "FINISHED"})])
        result = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=items[0].id, client=_client(fake))
        assert result["published"] is True, result
        publication = db.get(GrowthPublication, items[0].publication_id)
        assert publication is not None and publication.format == "reel" and publication.permalink.startswith("https://")
        assert _step(overview(db, admin.tenant_id), "instagram_reel")["status"] != "verified_live"
        assert publisher.publish_due(db, tenant_id=admin.tenant_id) == 0
        assert _mode() == before
    finally:
        db.rollback()
        db.close()
