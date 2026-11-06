"""Expiry, revocation, a second scheduler tick, and an unknown publish effect.

The Graph client is a scripted fake. Publishing mode stays disabled unless a
test passes that fake in directly, so no live Meta client is opened.
"""

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import get_session
from app.models.assessment import ExternalEffect
from app.models.growth import GrowthPublication
from app.services.growth import publisher
from app.services.growth.acceptance import authorize
from app.services.growth.common import now
from app.services.organic_metrics import collect_due_organic_metrics
from tests.growth_support import FakeGraph, network_error, ok
from tests.test_growth_publishing import IG, _client, _instagram_routes, _ready


def test_expired_and_revoked_credentials_never_reach_meta(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, account, items = _ready(db, monkeypatch, count=3)
        account.token_expires_at = now() - timedelta(minutes=1)
        db.flush()
        fake = FakeGraph()
        expired = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=items[0].id, client=_client(fake))
        assert expired["published"] is False and "expired" in expired["detail"].lower()
        assert fake.calls == []

        account.token_expires_at = now() + timedelta(days=30)
        account.data_access_expires_at = now() - timedelta(minutes=1)
        db.flush()
        access = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=items[1].id, client=_client(fake))
        assert access["published"] is False and "data access" in access["detail"].lower()

        account.data_access_expires_at = now() + timedelta(days=30)
        account.status = "revoked"
        db.flush()
        revoked = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=items[2].id, client=_client(fake))
        assert revoked["published"] is False and "disconnected" in revoked["detail"].lower()
        assert fake.calls == []
        assert db.scalar(select(func.count()).select_from(GrowthPublication).where(GrowthPublication.tenant_id == admin.tenant_id)) == 0
    finally:
        db.rollback()
        db.close()


def test_a_second_scheduler_tick_does_not_publish_twice(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch)
        fake = _instagram_routes(FakeGraph())
        graph = _client(fake)
        monkeypatch.setattr(get_settings(), "social_growth_publish_mode", "live")
        monkeypatch.setattr("app.services.growth.publisher.live_client", lambda *_args, **_kwargs: graph)
        assert publisher.publish_due(db, tenant_id=admin.tenant_id) == 0
        assert fake.calls == []
        authorize(db, tenant_id=admin.tenant_id, actor_id=admin.id, step_key="instagram_image", note="Scheduler check for one Instagram image.")
        assert publisher.publish_due(db, tenant_id=admin.tenant_id) == 1
        assert publisher.publish_due(db, tenant_id=admin.tenant_id) == 0
        assert fake.count("POST", r"/media_publish$") == 1
        effects = db.scalar(
            select(func.count()).select_from(ExternalEffect).where(
                ExternalEffect.tenant_id == admin.tenant_id,
                ExternalEffect.action == "social.growth_publish",
                ExternalEffect.target_id == str(items[0].id),
            )
        )
        assert effects == 1
    finally:
        db.rollback()
        db.close()


def test_an_unknown_effect_is_reconciled_before_another_post(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, _account, items = _ready(db, monkeypatch)
        fake = _instagram_routes(
            FakeGraph(),
            statuses=[ok({"status_code": "FINISHED"}), network_error()],
            publish=[network_error()],
        )
        fake.routes = [route for route in fake.routes if not (route[0] == "GET" and route[1].pattern == f"^{IG}/media$")]
        fake.on("GET", rf"^{IG}/media$", [ok({"data": []})])
        first = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=items[0].id, client=_client(fake))
        assert first["published"] is False and "unknown" in first["detail"].lower()
        publication = db.get(GrowthPublication, items[0].publication_id)
        effect = db.scalar(select(ExternalEffect).where(ExternalEffect.effect_key == publication.effect_key))
        assert publication.status == "unknown" and effect.outcome == "unknown"
        second = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=None, item_id=items[0].id, client=_client(fake))
        assert second["published"] is False
        assert fake.count("POST", r"/media_publish$") == 1
        assert db.scalar(select(func.count()).select_from(ExternalEffect).where(ExternalEffect.effect_key == publication.effect_key)) == 1
    finally:
        db.rollback()
        db.close()


def test_organic_metrics_for_one_tenant_do_not_scan_another(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        assert collect_due_organic_metrics(db, tenant_id=uuid4()) == 0
    finally:
        db.rollback()
        db.close()
