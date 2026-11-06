"""Acceptance status is computed. A fixture or scripted result is never live-verified.

Authorization writes a decision and does not construct a provider client.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session
from app.models.growth import GrowthMedia, GrowthMetricObservation, GrowthPublication, GrowthTrafficObservation
from app.services.growth import publisher
from app.services.growth.acceptance import authorize, overview
from app.services.growth.accounts import create_fixture_account
from app.services.growth.common import dumps, now
from app.services.organic_metrics import collect_due_organic_metrics
from tests.growth_support import FakeGraph, live_account, user
from tests.test_growth_publishing import _client, _instagram_routes, _ready


def _step(rows: list[dict], key: str) -> dict:
    return next(row for row in rows if row["step_key"] == key)


def test_fixture_and_scripted_results_are_not_live_verified(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        fixture = create_fixture_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform="facebook", name="Fixture Page")
        fixture.status = "connected"
        fixture.last_verified_at = now()
        fixture.capabilities = dumps({"publish": True, "insights": True, "checked": True, "evidence": "provider"})
        account = live_account(db, admin.tenant_id, admin, "facebook", "100000000000002")
        account.status = "connected"
        account.capabilities = dumps({"publish": True, "insights": True, "checked": True, "evidence": "provider"})
        db.add(
            GrowthMedia(
                tenant_id=admin.tenant_id,
                account_id=account.id,
                external_id="historical-live-label",
                origin="historical",
                provenance="live",
            )
        )
        db.add(
            GrowthMetricObservation(
                tenant_id=admin.tenant_id,
                account_id=account.id,
                scope="account",
                external_id=account.external_id,
                metric="reach",
                period="day",
                period_key="2026-11-01",
                status="recorded",
                retrieved_at=now(),
                provenance="live",
            )
        )
        db.add(
            GrowthTrafficObservation(
                tenant_id=admin.tenant_id,
                property_id="properties/1",
                day="2026-11-01",
                retrieved_at=now(),
                provenance="live",
            )
        )
        db.flush()
        before = overview(db, admin.tenant_id)
        assert _step(before, "token_verification")["status"] == "failed"
        assert _step(before, "history_import")["status"] != "verified_live"
        assert _step(before, "meta_insights")["status"] != "verified_live"
        assert _step(before, "ga4")["status"] != "verified_live"
        assert all(row["status"] != "verified_live" for row in before)

        authorize(db, tenant_id=admin.tenant_id, actor_id=admin.id, step_key="token_verification", note="Verify the Northwind Facebook Page token.")
        token = _step(overview(db, admin.tenant_id), "token_verification")
        assert token["status"] == "verified_live"
        assert "fixture" not in token["reason"].casefold()

        other = overview(db, uuid4())
        assert _step(other, "token_verification")["status"] != "verified_live"
        assert collect_due_organic_metrics(db, tenant_id=uuid4()) == 0
    finally:
        db.rollback()
        db.close()


def test_a_scripted_publish_is_not_live_verified_until_marked_provider(client: TestClient, monkeypatch) -> None:
    _ = client
    db = get_session()
    try:
        admin, _account, _items = _ready(db, monkeypatch)
        fake = _instagram_routes(FakeGraph())
        result = publisher.publish_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=_items[0].id, client=_client(fake))
        assert result["published"] is True
        publication = db.scalar(select(GrowthPublication).where(GrowthPublication.tenant_id == admin.tenant_id))
        assert publication is not None and publication.provenance == "live"
        assert _step(overview(db, admin.tenant_id), "instagram_image")["status"] != "verified_live"
        publication.provenance = "provider"
        publication.status = "published"
        db.flush()
        unauthorized = _step(overview(db, admin.tenant_id), "instagram_image")
        assert unauthorized["status"] == "failed"
        authorize(db, tenant_id=admin.tenant_id, actor_id=admin.id, step_key="instagram_image", note="One Instagram image for the Northwind account.")
        verified = _step(overview(db, admin.tenant_id), "instagram_image")
        assert verified["status"] == "verified_live"
        assert fake.count("POST", r"/media_publish$") == 1
    finally:
        db.rollback()
        db.close()
