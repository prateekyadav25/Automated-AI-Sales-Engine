"""Google Meet booking with a scripted Calendar client.

The event ids below are fixture ids. They are not a live Google Calendar.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.db.session import get_session
from app.models.acquisition import InboundCapture
from app.models.ai import AIApproval
from app.models.crm import Lead, Opportunity
from app.models.execution import JourneyLink
from app.models.identity import Tenant, User
from app.models.integrations import EmailMessage, ProviderAccount, ProviderAction
from app.models.lifecycle import MeetingRecord, Product, SequenceEnrollment
from app.models.operating_plan import DemoScope, OperatingPlan
from app.providers.calendar import NO_LIVE_CALENDAR, GoogleCalendarProvider
from app.services.autopilot_settings import get_or_create_settings
from app.services.demo_guard import EXPIRED_BLOCK, PREPARED_BLOCK
from app.services.dispatcher import dispatch_approval
from app.services.meet_booking import (
    authorize_meet_booking,
    authorize_meet_change,
    execute_meet_booking,
    execute_meet_cancel,
    execute_meet_reschedule,
    meeting_booking_view,
    propose_meet_slots,
    record_meeting_request,
    select_meet_slot,
    wall_to_utc,
)
from tests.test_organic_acquisition import _close_scopes, _user


class Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class Scripted:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.free: list[tuple[int, dict]] = [(200, {"calendars": {"primary": {"busy": []}}})]
        self.insert: tuple[int, dict] | None = None
        self.read: tuple[int, dict] = (404, {})
        self.patch_result: tuple[int, dict] = (200, {})
        self.delete_status = 204

    def post(self, url: str, headers=None, content=None, timeout=None) -> Response:
        _ = timeout
        body = json.loads(content or "{}")
        self.calls.append({"method": "POST", "url": url, "body": body})
        if "freeBusy" in url:
            status, payload = self.free.pop(0)
            return Response(status, payload)
        status, payload = self.insert or (500, {})
        return Response(status, payload)

    def get(self, url: str, headers=None, timeout=None) -> Response:
        _ = headers, timeout
        self.calls.append({"method": "GET", "url": url, "body": {}})
        status, payload = self.read
        return Response(status, payload)

    def patch(self, url: str, headers=None, content=None, timeout=None) -> Response:
        _ = headers, content, timeout
        self.calls.append({"method": "PATCH", "url": url, "body": json.loads(content or "{}")})
        status, payload = self.patch_result
        return Response(status, payload)

    def delete(self, url: str, headers=None, timeout=None) -> Response:
        _ = headers, timeout
        self.calls.append({"method": "DELETE", "url": url, "body": {}})
        return Response(self.delete_status, {})


def _id(value: str) -> UUID:
    return UUID(value)


def _provider(scripted: Scripted) -> GoogleCalendarProvider:
    return GoogleCalendarProvider(
        access_token="fixture-token",
        http_post=scripted.post,
        http_get=scripted.get,
        http_patch=scripted.patch,
        http_delete=scripted.delete,
    )


def _success(event_id: str = "evtfixture0001") -> dict:
    return {
        "id": event_id,
        "conferenceData": {
            "conferenceId": "conf-fixture-1",
            "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/fixture-abc-def"}],
            "createRequest": {"status": {"statusCode": "success"}},
        },
    }


@pytest.fixture(autouse=True)
def _no_live_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        _ = args, kwargs
        raise AssertionError("a live Google client was constructed")

    monkeypatch.setattr("httpx.post", boom)
    monkeypatch.setattr("httpx.get", boom)
    monkeypatch.setattr("httpx.patch", boom)
    monkeypatch.setattr("httpx.delete", boom)


def _open_lab(db, user: User) -> None:
    _close_scopes(db, user.tenant_id)
    tenant = db.get(Tenant, user.tenant_id)
    assert tenant is not None
    tenant.operating_mode = "LIVE"
    settings = get_or_create_settings(db, tenant_id=user.tenant_id, actor_id=user.id)
    settings.timezone = "Asia/Kolkata"


def _lead(db, user: User, note: str = "Can we meet next week about the router?") -> tuple[Lead, InboundCapture]:
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
    plan = OperatingPlan(
        tenant_id=user.tenant_id,
        created_by=user.id,
        product_id=product.id,
        channel="linkedin",
        audience="Operations leads",
        status="running",
    )
    db.add(plan)
    db.flush()
    lead = Lead(
        tenant_id=user.tenant_id,
        created_by=user.id,
        first_name="Nia",
        last_name="North",
        email=f"nia.{uuid4().hex[:8]}@example.com",
        company_name="Northline",
        owner_id=user.id,
        operating_plan_id=plan.id,
        notes=note,
        status="qualified",
    )
    db.add(lead)
    db.flush()
    capture = InboundCapture(
        tenant_id=user.tenant_id,
        created_by=user.id,
        lead_id=lead.id,
        first_name="Nia",
        last_name="North",
        email=lead.email,
        request_note=note,
        consent_email=True,
    )
    db.add(capture)
    db.flush()
    existing = db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.tenant_id == user.tenant_id,
            ProviderAccount.provider == "google",
            ProviderAccount.connected_user_id == user.id,
            ProviderAccount.status == "connected",
            ProviderAccount.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return lead, capture
    account = ProviderAccount(
        tenant_id=user.tenant_id,
        created_by=user.id,
        provider="google",
        account_key=f"owner-{uuid4().hex[:8]}",
        provider_account_id="primary",
        connected_user_id=user.id,
        status="connected",
        scopes=json.dumps(
            [
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.readonly",
            ]
        ),
    )
    db.add(account)
    db.flush()
    return lead, capture


def _booked(db, user: User, scripted: Scripted) -> tuple[Lead, MeetingRecord, AIApproval]:
    if scripted.insert is None:
        scripted.insert = (200, _success())
    if len(scripted.free) < 2:
        scripted.free = [
            (200, {"calendars": {"primary": {"busy": []}}}),
            (200, {"calendars": {"primary": {"busy": []}}}),
        ]
    lead, capture = _lead(db, user)
    requested = record_meeting_request(
        db, tenant_id=user.tenant_id, actor_id=user.id, lead=lead, note=capture.request_note, capture_id=capture.id
    )
    meeting_id = requested["meeting_id"]
    proposed = propose_meet_slots(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        meeting_id=meeting_id,
        provider=_provider(scripted),
        attendee_timezone="America/New_York",
    )
    slot = proposed["slots"][0]
    select_meet_slot(db, tenant_id=user.tenant_id, meeting_id=meeting_id, start=slot["start"], end=slot["end"])
    authorized = authorize_meet_booking(
        db, tenant_id=user.tenant_id, actor_id=user.id, meeting_id=meeting_id, approved=True, invite=False
    )
    approval = db.get(AIApproval, _id(authorized["approval_id"]))
    assert approval is not None
    execute_meet_booking(db, tenant_id=user.tenant_id, actor_id=user.id, approval=approval, provider=_provider(scripted))
    meeting = db.get(MeetingRecord, _id(meeting_id))
    assert meeting is not None
    return lead, meeting, approval


def test_meet_booking_journey_is_labeled_and_replay_safe(client) -> None:
    _ = client
    db = get_session()
    scripted = Scripted()
    try:
        user = _user(db)
        _open_lab(db, user)
        before_email = db.scalar(select(func.count()).select_from(EmailMessage)) or 0
        before_opportunity = db.scalar(select(func.count()).select_from(Opportunity)) or 0
        before_enrollment = db.scalar(select(func.count()).select_from(SequenceEnrollment)) or 0
        lead, meeting, approval = _booked(db, user, scripted)
        assert meeting.status == "booked"
        assert meeting.is_mock is True
        assert meeting.provider_event_id == "evtfixture0001"
        assert meeting.conference_id == "conf-fixture-1"
        assert meeting.join_url == "https://meet.google.com/fixture-abc-def"
        assert meeting.client_event_id != meeting.conference_id
        assert meeting.provider_event_id != meeting.conference_id
        context = json.loads(meeting.context_json)
        assert context["customer_facing_name"] == "Northline Desk Router"
        assert context["sku"] == "NDR"
        view = meeting_booking_view(db, meeting)
        assert view["fixture"] is True
        assert view["join_url"] == ""
        assert view["fixture_join_url"] == meeting.join_url
        assert view["live_execution_ready"] is False
        assert "Attendance" in view["attendance"]
        assert view["owner_name"] == user.name
        assert view["calendar_id"] == "primary"
        creates = [call for call in scripted.calls if call["method"] == "POST" and "/events?" in call["url"]]
        assert len(creates) == 1
        assert "conferenceDataVersion=1" in creates[0]["url"]
        assert "sendUpdates=none" in creates[0]["url"]
        assert creates[0]["body"]["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
        assert creates[0]["body"]["attendees"] == []
        assert creates[0]["body"]["id"] == meeting.client_event_id
        slots = json.loads(meeting.slots_json)
        assert slots[0]["owner_timezone"] == "Asia/Kolkata"
        assert slots[0]["attendee_timezone"] == "America/New_York"
        assert slots[0]["owner_local"] != slots[0]["attendee_local"]
        execute_meet_booking(db, tenant_id=user.tenant_id, actor_id=user.id, approval=approval, provider=_provider(scripted))
        assert len([call for call in scripted.calls if call["method"] == "POST" and "/events?" in call["url"]]) == 1
        linked = db.scalar(
            select(JourneyLink).where(JourneyLink.entity_type == "meeting", JourneyLink.entity_id == str(meeting.id))
        )
        assert linked is not None
        assert lead.status == "meeting_scheduled"
        assert db.scalar(select(func.count()).select_from(EmailMessage)) == before_email
        assert db.scalar(select(func.count()).select_from(Opportunity)) == before_opportunity
        assert db.scalar(select(func.count()).select_from(SequenceEnrollment)) == before_enrollment
        repeated = record_meeting_request(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            lead=lead,
            note="Can we meet next week about the router?",
            capture_id=meeting.capture_id,
        )
        assert repeated["meeting_id"] == str(meeting.id)
    finally:
        db.rollback()
        db.close()


def test_request_authorization_and_identity_guards(client) -> None:
    _ = client
    db = get_session()
    scripted = Scripted()
    try:
        user = _user(db)
        _open_lab(db, user)
        lead, _capture = _lead(db, user, note="This account is qualified for the router.")
        refused = record_meeting_request(
            db, tenant_id=user.tenant_id, actor_id=user.id, lead=lead, note="This account is qualified for the router."
        )
        assert refused["status"] == "not_requested"
        assert db.scalar(select(func.count()).select_from(MeetingRecord).where(MeetingRecord.lead_id == lead.id)) == 0
        lead.notes = "Can we meet next week?"
        captured = InboundCapture(
            tenant_id=user.tenant_id,
            created_by=user.id,
            lead_id=lead.id,
            first_name="Nia",
            last_name="North",
            email=lead.email,
            request_note="Can we meet next week?",
        )
        db.add(captured)
        db.flush()
        requested = record_meeting_request(
            db, tenant_id=user.tenant_id, actor_id=user.id, lead=lead, note=captured.request_note, capture_id=uuid4()
        )
        meeting = db.get(MeetingRecord, _id(requested["meeting_id"]))
        assert meeting is not None
        assert meeting.capture_id is None
        email_approval = AIApproval(
            tenant_id=user.tenant_id,
            created_by=user.id,
            action_level=2,
            action_type="email.send",
            title="Send times",
            payload_json=json.dumps({"meeting_id": str(meeting.id)}),
            status="approved",
            entity_type="meeting",
            entity_id=str(meeting.id),
            idempotency_key=f"email-{uuid4().hex}",
        )
        db.add(email_approval)
        db.flush()
        blocked = execute_meet_booking(
            db, tenant_id=user.tenant_id, actor_id=user.id, approval=email_approval, provider=_provider(scripted)
        )
        assert blocked["status"] == "not_authorized"
        assert scripted.calls == []
        other = Tenant(name="Other workspace", slug=f"other-{uuid4().hex[:8]}", operating_mode="LIVE")
        db.add(other)
        db.flush()
        db.add(
            ProviderAccount(
                tenant_id=other.id,
                created_by=user.id,
                provider="google",
                account_key="foreign",
                provider_account_id="foreign-calendar",
                connected_user_id=user.id,
                status="connected",
                scopes=json.dumps(["https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.readonly"]),
            )
        )
        owned = db.scalar(select(ProviderAccount).where(ProviderAccount.tenant_id == user.tenant_id, ProviderAccount.connected_user_id == user.id))
        assert owned is not None
        owned.status = "revoked"
        db.flush()
        proposed = propose_meet_slots(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            meeting_id=meeting.id,
            provider=_provider(scripted),
            attendee_timezone="America/New_York",
        )
        assert "revoked" in proposed["blocker"]
        assert scripted.calls == []
        assert meeting.calendar_id != "foreign-calendar"
    finally:
        db.rollback()
        db.close()


def test_conflict_unknown_pending_and_permission(client) -> None:
    _ = client
    db = get_session()
    try:
        user = _user(db)
        _open_lab(db, user)
        conflict = Scripted()
        conflict.free = [
            (200, {"calendars": {"primary": {"busy": []}}}),
            (
                200,
                {
                    "calendars": {
                        "primary": {
                            "busy": [{"start": "2020-01-01T00:00:00Z", "end": "2035-01-01T00:00:00Z"}]
                        }
                    }
                },
            ),
        ]
        lead, capture = _lead(db, user)
        requested = record_meeting_request(
            db, tenant_id=user.tenant_id, actor_id=user.id, lead=lead, note=capture.request_note, capture_id=capture.id
        )
        proposed = propose_meet_slots(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            meeting_id=requested["meeting_id"],
            provider=_provider(conflict),
            attendee_timezone="UTC",
        )
        slot = proposed["slots"][0]
        select_meet_slot(db, tenant_id=user.tenant_id, meeting_id=requested["meeting_id"], start=slot["start"], end=slot["end"])
        authorized = authorize_meet_booking(
            db, tenant_id=user.tenant_id, actor_id=user.id, meeting_id=requested["meeting_id"], approved=True
        )
        approval = db.get(AIApproval, _id(authorized["approval_id"]))
        assert approval is not None
        refused = execute_meet_booking(
            db, tenant_id=user.tenant_id, actor_id=user.id, approval=approval, provider=_provider(conflict)
        )
        assert "conflict" in refused["blocker"]
        assert not any("/events?" in call["url"] for call in conflict.calls)

        unknown = Scripted()
        unknown.insert = (200, {})
        unknown.read = (200, _success("evtfromread0001"))
        _lead_row, meeting, approval = _booked(db, user, unknown)
        assert meeting.status == "needs_review"
        assert "not repeated" in meeting.blocker
        assert meeting.provider_event_id in {None, ""}
        execute_meet_booking(db, tenant_id=user.tenant_id, actor_id=user.id, approval=approval, provider=_provider(unknown))
        assert len([call for call in unknown.calls if call["method"] == "POST" and "/events?" in call["url"]]) == 1
        assert meeting.status == "booked"
        assert meeting.provider_event_id == "evtfromread0001"
        assert any(call["method"] == "GET" for call in unknown.calls)

        pending = Scripted()
        pending.insert = (
            200,
            {"id": "evtpending0001", "conferenceData": {"createRequest": {"status": {"statusCode": "pending"}}}},
        )
        pending.read = (
            200,
            {"id": "evtpending0001", "conferenceData": {"createRequest": {"status": {"statusCode": "pending"}}}},
        )
        _lead_row, meeting, approval = _booked(db, user, pending)
        assert meeting.status == "conference_pending"
        assert meeting.join_url == ""
        execute_meet_booking(db, tenant_id=user.tenant_id, actor_id=user.id, approval=approval, provider=_provider(pending))
        assert len([call for call in pending.calls if call["method"] == "POST" and "/events?" in call["url"]]) == 1
        assert meeting.status == "conference_pending"

        failed = Scripted()
        failed.insert = (
            200,
            {
                "id": "evtfailed00001",
                "conferenceData": {"conferenceId": "conf-failed", "createRequest": {"status": {"statusCode": "failure"}}},
            },
        )
        _lead_row, meeting, approval = _booked(db, user, failed)
        assert meeting.status == "needs_review"
        assert meeting.provider_event_id == "evtfailed00001"
        assert meeting.join_url == ""
        execute_meet_booking(db, tenant_id=user.tenant_id, actor_id=user.id, approval=approval, provider=_provider(failed))
        assert len([call for call in failed.calls if call["method"] == "POST" and "/events?" in call["url"]]) == 1

        denied = Scripted()
        denied.insert = (403, {"error": {"status": "PERMISSION_DENIED"}})
        _lead_row, meeting, _approval = _booked(db, user, denied)
        assert meeting.status == "needs_review"
        assert "permission" in meeting.blocker.lower()
        limited = Scripted()
        limited.insert = (429, {})
        _lead_row, meeting, _approval = _booked(db, user, limited)
        assert "rate limited" in meeting.blocker.lower()
    finally:
        db.rollback()
        db.close()


def test_reschedule_cancel_and_stale_jobs(client) -> None:
    _ = client
    db = get_session()
    scripted = Scripted()
    try:
        user = _user(db)
        _open_lab(db, user)
        scripted.patch_result = (200, _success("evtfixture0001"))
        _lead_row, meeting, _approval = _booked(db, user, scripted)
        scripted.free.append((200, {"calendars": {"primary": {"busy": []}}}))
        first = authorize_meet_change(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            meeting_id=meeting.id,
            kind="reschedule",
            approved=True,
            start="2030-01-08T04:30:00+00:00",
            end="2030-01-08T05:00:00+00:00",
        )
        second = authorize_meet_change(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            meeting_id=meeting.id,
            kind="reschedule",
            approved=True,
            start="2030-01-09T04:30:00+00:00",
            end="2030-01-09T05:00:00+00:00",
        )
        stale = db.get(AIApproval, _id(first["approval_id"]))
        current = db.get(AIApproval, _id(second["approval_id"]))
        assert stale is not None and current is not None
        before = len([call for call in scripted.calls if call["method"] == "PATCH"])
        stale_result = execute_meet_reschedule(
            db, tenant_id=user.tenant_id, actor_id=user.id, approval=stale, provider=_provider(scripted)
        )
        assert "stale" in stale_result["blocker"]
        assert len([call for call in scripted.calls if call["method"] == "PATCH"]) == before
        moved = execute_meet_reschedule(
            db, tenant_id=user.tenant_id, actor_id=user.id, approval=current, provider=_provider(scripted)
        )
        assert moved["status"] == "rescheduled"
        assert meeting.join_url == "https://meet.google.com/fixture-abc-def"
        patches = [call for call in scripted.calls if call["method"] == "PATCH"]
        assert len(patches) == 1
        assert "sendUpdates=none" in patches[0]["url"]
        assert "conferenceDataVersion=1" in patches[0]["url"]
        cancelled = authorize_meet_change(
            db, tenant_id=user.tenant_id, actor_id=user.id, meeting_id=meeting.id, kind="cancel", approved=True
        )
        cancel_approval = db.get(AIApproval, _id(cancelled["approval_id"]))
        assert cancel_approval is not None
        done = execute_meet_cancel(
            db, tenant_id=user.tenant_id, actor_id=user.id, approval=cancel_approval, provider=_provider(scripted)
        )
        assert done["status"] == "cancelled"
        assert any(call["method"] == "DELETE" and "sendUpdates=none" in call["url"] for call in scripted.calls)
        posts_before = len([call for call in scripted.calls if call["method"] == "POST" and "/events?" in call["url"]])
        again = execute_meet_booking(
            db, tenant_id=user.tenant_id, actor_id=user.id, approval=_approval, provider=_provider(scripted)
        )
        assert again["status"] == "cancelled"
        assert len([call for call in scripted.calls if call["method"] == "POST" and "/events?" in call["url"]]) == posts_before
    finally:
        db.rollback()
        db.close()


def test_scopes_block_before_any_calendar_call(client) -> None:
    _ = client
    db = get_session()
    scripted = Scripted()
    try:
        user = _user(db)
        lead, capture = _lead(db, user)
        db.add(
            DemoScope(
                tenant_id=user.tenant_id,
                created_by=user.id,
                status="prepared",
                expires_at=datetime(2026, 10, 29, 18, 3, tzinfo=UTC),
                allowed_actions="{}",
            )
        )
        db.flush()
        requested = record_meeting_request(
            db, tenant_id=user.tenant_id, actor_id=user.id, lead=lead, note=capture.request_note, capture_id=capture.id
        )
        prepared = propose_meet_slots(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            meeting_id=requested["meeting_id"],
            provider=_provider(scripted),
            attendee_timezone="UTC",
        )
        assert prepared["blocker"] == PREPARED_BLOCK
        assert scripted.calls == []
        _close_scopes(db, user.tenant_id)
        db.flush()
        missing = propose_meet_slots(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            meeting_id=requested["meeting_id"],
            provider=_provider(scripted),
            attendee_timezone="UTC",
        )
        assert "outside this demonstration" in missing["blocker"]
        assert scripted.calls == []
        tenant = db.get(Tenant, user.tenant_id)
        assert tenant is not None
        tenant.operating_mode = "LIVE"
        db.add(
            DemoScope(
                tenant_id=user.tenant_id,
                created_by=user.id,
                status="expired",
                expires_at=datetime.now(UTC),
                allowed_actions="{}",
            )
        )
        db.flush()
        expired = propose_meet_slots(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            meeting_id=requested["meeting_id"],
            provider=_provider(scripted),
            attendee_timezone="UTC",
        )
        assert expired["blocker"] == EXPIRED_BLOCK
        assert scripted.calls == []
        actions = db.scalar(
            select(func.count()).select_from(ProviderAction).where(ProviderAction.entity_id == requested["meeting_id"])
        )
        assert actions == 0
    finally:
        db.rollback()
        db.close()


def test_worker_refuses_a_live_calendar_client(client) -> None:
    _ = client
    db = get_session()
    scripted = Scripted()
    try:
        user = _user(db)
        _open_lab(db, user)
        lead, capture = _lead(db, user)
        requested = record_meeting_request(
            db, tenant_id=user.tenant_id, actor_id=user.id, lead=lead, note=capture.request_note, capture_id=capture.id
        )
        proposed = propose_meet_slots(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            meeting_id=requested["meeting_id"],
            provider=_provider(scripted),
            attendee_timezone="UTC",
        )
        slot = proposed["slots"][0]
        select_meet_slot(db, tenant_id=user.tenant_id, meeting_id=requested["meeting_id"], start=slot["start"], end=slot["end"])
        authorized = authorize_meet_booking(
            db, tenant_id=user.tenant_id, actor_id=user.id, meeting_id=requested["meeting_id"], approved=True
        )
        approval = db.get(AIApproval, _id(authorized["approval_id"]))
        assert approval is not None
        message = dispatch_approval(db, tenant_id=user.tenant_id, actor_id=user.id, row=approval)
        assert message == NO_LIVE_CALENDAR
        assert not any("/events?" in call["url"] for call in scripted.calls)
        meeting = db.get(MeetingRecord, _id(requested["meeting_id"]))
        assert meeting is not None
        assert meeting.provider_event_id in {None, ""}
        scripted.insert = (200, _success())
        scripted.free.append((200, {"calendars": {"primary": {"busy": []}}}))
        execute_meet_booking(db, tenant_id=user.tenant_id, actor_id=user.id, approval=approval, provider=_provider(scripted))
        posts = len([call for call in scripted.calls if call["method"] == "POST" and "/events?" in call["url"]])
        again = dispatch_approval(db, tenant_id=user.tenant_id, actor_id=user.id, row=approval)
        assert again == "booked" or meeting.status == "booked"
        assert meeting.join_url == "https://meet.google.com/fixture-abc-def"
        assert len([call for call in scripted.calls if call["method"] == "POST" and "/events?" in call["url"]]) == posts
    finally:
        db.rollback()
        db.close()


def test_daylight_saving_wall_times_are_not_guessed() -> None:
    zone = ZoneInfo("America/New_York")
    assert wall_to_utc(datetime(2026, 3, 8, 2, 30), zone) is None
    assert wall_to_utc(datetime(2026, 11, 1, 1, 30), zone) is None
    valid = wall_to_utc(datetime(2026, 3, 9, 9, 30), zone)
    assert valid is not None
    assert valid.tzinfo is not None
    assert valid.astimezone(zone).hour == 9
