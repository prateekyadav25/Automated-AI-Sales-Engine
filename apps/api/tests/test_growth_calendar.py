"""Strategy approval and the rolling 30-day calendar. No provider is called."""

from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session
from app.models.ai import AIApproval
from app.models.growth import GrowthCalendarItem, GrowthCreative
from app.models.identity import AuditLog
from app.services.growth import accounts as account_service
from app.services.growth import brand as brand_service
from app.services.growth import creative as creative_service
from app.services.growth import planner
from app.services.growth import strategy as strategy_service
from tests.conftest import login
from tests.growth_support import approved_brand, approved_strategy, form, user


def _items(db, tenant_id):
    return list(db.scalars(select(GrowthCalendarItem).where(GrowthCalendarItem.tenant_id == tenant_id, GrowthCalendarItem.deleted_at.is_(None))).all())


def test_rolling_calendar_respects_windows_and_explains_every_slot(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        facts = approved_brand(db, admin.tenant_id, admin)
        instagram = account_service.create_fixture_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform="instagram", name="Northwind IG")
        facebook = account_service.create_fixture_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform="facebook", name="Northwind Page")
        instagram.timezone = "Asia/Kolkata"
        facebook.timezone = "Asia/Kolkata"
        facebook.posting_windows = '[{"days": [1, 3], "start": "10:00", "end": "12:00"}]'
        destination = form(db, admin.tenant_id, admin)
        assert planner.plan_rolling_calendar(db, tenant_id=admin.tenant_id, actor_id=admin.id)["status"] == "blocked"
        event = strategy_service.save_event(
            db,
            tenant_id=admin.tenant_id,
            actor_id=admin.id,
            title="Monsoon cold-chain checks",
            kind="announcement",
            starts_on=(date.today() + timedelta(days=10)).isoformat(),
            ends_on=(date.today() + timedelta(days=12)).isoformat(),
            details="Operator-recorded event.",
            fact_ids=[str(facts["cold"].id)],
            source_url="https://northwind.example/services",
        )
        strategy = approved_strategy(db, admin.tenant_id, admin, facts, [instagram, facebook], destination)
        result = planner.plan_rolling_calendar(db, tenant_id=admin.tenant_id, actor_id=admin.id)
        assert result["status"] == "planned"
        items = _items(db, admin.tenant_id)
        assert result["created"] == len(items) > 0
        zone = ZoneInfo("Asia/Kolkata")
        horizon_end = datetime.now(zone) + timedelta(days=31)
        ig_items = [row for row in items if row.account_id == instagram.id]
        fb_items = [row for row in items if row.account_id == facebook.id]
        assert 11 <= len(ig_items) <= 15
        assert 7 <= len(fb_items) <= 10
        for row in items:
            local = row.planned_for.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone) if row.planned_for.tzinfo is None else row.planned_for.astimezone(zone)
            assert local <= horizon_end
            if row.account_id == facebook.id:
                assert local.weekday() in {1, 3} and 10 <= local.hour < 12
            else:
                assert local.weekday() <= 4 and 9 <= local.hour < 18
            assert row.format in ({"image", "carousel"} if row.account_id == instagram.id else {"image"})
            brief = planner.loads(row.brief_json, {})
            assert brief["facts"] and all(fact["source_url"].startswith("https://") for fact in brief["facts"])
            assert {fact["id"] for fact in brief["facts"]} <= {str(fact.id) for fact in facts.values()}
            assert brief["repetition"]["threshold"] == planner.SIMILARITY_THRESHOLD
            assert brief["performance"]["verdict"] == "insufficient_evidence"
            assert brief["call_to_action"] == "Ask for a route quote"
            assert brief["rationale"]
            assert row.status == "planned"
        in_event = [row for row in items if event.starts_on <= row.local_date <= event.ends_on]
        assert in_event and all(planner.loads(row.brief_json, {})["event"]["id"] == str(event.id) for row in in_event)
        pillars = {row.pillar_key for row in ig_items}
        assert pillars == {"offer", "proof"}
        consecutive = sorted(ig_items, key=lambda row: row.planned_for)
        assert all(left.pillar_key != right.pillar_key for left, right in zip(consecutive, consecutive[1:], strict=False))
        again = planner.plan_rolling_calendar(db, tenant_id=admin.tenant_id, actor_id=admin.id)
        assert again["created"] == 0 and again["kept"] >= len(items) - 2
        assert len(_items(db, admin.tenant_id)) == len(items)
        draft = strategy_service.save_strategy(
            db,
            tenant_id=admin.tenant_id,
            actor_id=admin.id,
            payload={**strategy_service.strategy_out(strategy), "pillars": [{"key": "offer", "name": "What we move", "fact_ids": [str(facts["cold"].id)]}], "destination_form_key_id": str(destination.id)},
        )
        assert draft.version == strategy.version + 1 and draft.status == "draft"
        assert strategy_service.active_strategy(db, admin.tenant_id).id == strategy.id
        strategy_service.approve_strategy(db, tenant_id=admin.tenant_id, actor_id=admin.id, strategy_id=draft.id)
        db.refresh(strategy)
        assert strategy.status == "superseded"
        replanned = planner.plan_rolling_calendar(db, tenant_id=admin.tenant_id, actor_id=admin.id)
        assert replanned["replanned"] > 0
        assert {row.pillar_key for row in _items(db, admin.tenant_id) if row.status == "planned" and row.strategy_id == draft.id} == {"offer"}
        other = user(db, "admin@northline.demo")
        view = planner.calendar_view(db, other.tenant_id, start=datetime.now() - timedelta(days=1), end=datetime.now() + timedelta(days=40))
        assert view["items"] == []
        with pytest.raises(HTTPException) as missing:
            planner.owned_item(db, other.tenant_id, items[0].id)
        assert missing.value.status_code == 404
    finally:
        db.rollback()
        db.close()


def test_a_new_strategy_withdraws_unpublished_work_from_the_replaced_version(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        facts = approved_brand(db, admin.tenant_id, admin)
        account = account_service.create_fixture_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform="instagram", name="Northwind IG")
        destination = form(db, admin.tenant_id, admin)
        first = approved_strategy(db, admin.tenant_id, admin, facts, [account], destination)
        planner.plan_rolling_calendar(db, tenant_id=admin.tenant_id, actor_id=admin.id)
        drafted, scheduled, in_flight = sorted((row for row in _items(db, admin.tenant_id) if row.format == "image"), key=lambda row: row.planned_for)[1:4]
        drafted_view = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=drafted.id)
        scheduled_view = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=scheduled.id)
        creative_service.review_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, creative_id=UUID(scheduled_view["id"]), decision="approve", note="Facts and visuals checked.")
        request = creative_service.schedule_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=scheduled.id)
        assert request["authorization"] == "approval" and request["approval_id"]
        in_flight.status = "publishing"
        db.flush()

        draft = strategy_service.save_strategy(db, tenant_id=admin.tenant_id, actor_id=admin.id, payload={**strategy_service.strategy_out(first), "call_to_action": "Book a cold-chain audit", "destination_form_key_id": str(destination.id)})
        second = strategy_service.approve_strategy(db, tenant_id=admin.tenant_id, actor_id=admin.id, strategy_id=draft.id)
        result = planner.plan_rolling_calendar(db, tenant_id=admin.tenant_id, actor_id=admin.id)

        assert result["withdrawn"] == 2 and "withdrawn" in result["detail"]
        for item, view in ((drafted, drafted_view), (scheduled, scheduled_view)):
            db.refresh(item)
            assert (item.strategy_id, item.status, item.creative_id, item.tracking_link_id) == (second.id, "planned", None, None)
            assert db.get(GrowthCreative, UUID(view["id"])).status == "superseded"
            assert planner.loads(item.brief_json, {})["call_to_action"] == "Book a cold-chain audit"
        assert db.get(AIApproval, UUID(request["approval_id"])).status == "cancelled"
        db.refresh(in_flight)
        assert (in_flight.strategy_id, in_flight.status) == (first.id, "publishing")
        trail = db.scalars(select(AuditLog.entity_id).where(AuditLog.tenant_id == admin.tenant_id, AuditLog.action == "growth.item_superseded")).all()
        assert {str(drafted.id), str(scheduled.id)} <= set(trail)
        fresh = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=drafted.id)
        assert fresh["id"] != drafted_view["id"] and fresh["status"] in {"draft", "needs_review"}
    finally:
        db.rollback()
        db.close()


def test_strategy_cannot_cite_unapproved_facts_or_survive_a_rejection(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        facts = approved_brand(db, admin.tenant_id, admin)
        account = account_service.create_fixture_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform="instagram", name="IG")
        destination = form(db, admin.tenant_id, admin)
        pending = brand_service.add_operator_fact(db, tenant_id=admin.tenant_id, actor_id=admin.id, category="claim", statement="We are the fastest carrier.", source_url="https://northwind.example/", evidence="", approve=False)
        payload = {
            "objective": "Enquiries",
            "pillars": [{"key": "offer", "name": "Offer", "fact_ids": [pending["fact"]["id"]]}],
            "cadence": {str(account.id): {"formats": {"image": 2}}},
            "call_to_action": "Ask",
            "destination_kind": "form",
            "destination_form_key_id": str(destination.id),
        }
        with pytest.raises(HTTPException) as unapproved:
            strategy_service.save_strategy(db, tenant_id=admin.tenant_id, actor_id=admin.id, payload=payload)
        assert unapproved.value.status_code == 422
        payload["pillars"] = [{"key": "offer", "name": "Offer", "fact_ids": [str(facts["cold"].id)]}]
        payload["cadence"] = {str(account.id): {"formats": {"text": 1}}}
        with pytest.raises(HTTPException) as unsupported:
            strategy_service.save_strategy(db, tenant_id=admin.tenant_id, actor_id=admin.id, payload=payload)
        assert "does not support text" in str(unsupported.value.detail)
        payload["cadence"] = {str(account.id): {"formats": {"image": 2}}}
        draft = strategy_service.save_strategy(db, tenant_id=admin.tenant_id, actor_id=admin.id, payload=payload)
        brand_service.review_facts(db, tenant_id=admin.tenant_id, actor_id=admin.id, fact_ids=[facts["cold"].id], decision="reject", note="Wrong wording.")
        with pytest.raises(HTTPException) as changed:
            strategy_service.approve_strategy(db, tenant_id=admin.tenant_id, actor_id=admin.id, strategy_id=draft.id)
        assert changed.value.status_code == 422
    finally:
        db.rollback()
        db.close()


def test_calendar_routes_are_tenant_scoped(client: TestClient) -> None:
    northline = login(client, "admin@northline.demo")
    response = client.get("/api/v1/social-growth/calendar", headers=northline)
    assert response.status_code == 200
    assert all(item["account_id"] for item in response.json()["data"]["items"])
    missing = client.post("/api/v1/social-growth/calendar/00000000-0000-0000-0000-000000000001/creative", headers=northline)
    assert missing.status_code == 404
    reader = login(client, "readonly@agrayian.demo")
    assert client.post("/api/v1/social-growth/calendar/plan", headers=reader).status_code == 403
