"""Google Meet booking on the existing meeting and approval path.

A qualified lead is not a meeting request. A proposed slot and an approved
email are not booking permission. The live route never builds a Google
client. Fixture calls pass an explicit client. Prepared, missing, and expired
demonstration scopes are refused before that client is used.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.acquisition import InboundCapture
from app.models.ai import AIApproval
from app.models.crm import Lead
from app.models.identity import User
from app.models.integrations import ProviderAccount, ProviderAction
from app.models.lifecycle import MeetingRecord
from app.models.operating_plan import OperatingPlan
from app.providers.calendar import (
    NO_LIVE_CALENDAR,
    BusyPeriod,
    CalendarEventResult,
    GoogleCalendarProvider,
)
from app.services.audit import emit_event
from app.services.autopilot_settings import get_or_create_settings
from app.services.calendar_booking import _link_meeting
from app.services.crm import add_activity
from app.services.demo_guard import (
    EXPIRED_BLOCK,
    PREPARED_BLOCK,
    _operating_mode,
    _scope_expired,
    scope_for_execution,
)
from app.services.product_context import build_product_context
from app.services.provider_accounts import has_scopes
from app.services.provider_ops import begin_action, confirm_action

_REQUEST = re.compile(r"\b(meet|meeting|schedule a call|book a time)\b", re.IGNORECASE)
_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
_READ_SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar",
)
_MISSING_SCOPE = "Calendar booking stays outside this demonstration. No event was created."
_DURATION = timedelta(minutes=30)
_BUFFER = timedelta(minutes=15)
_NOTICE = timedelta(hours=4)
_HORIZON = timedelta(days=7)
_WORK_START = 9
_WORK_END = 17


def booking_scope_block(db: Session, tenant_id: UUID) -> str:
    scope = scope_for_execution(db, tenant_id)
    if scope is not None and _scope_expired(scope):
        return EXPIRED_BLOCK
    if scope is not None and scope.status == "prepared":
        return PREPARED_BLOCK
    if scope is None and _operating_mode(db, tenant_id) == "DEMO":
        return _MISSING_SCOPE
    return ""


def wall_to_utc(local_naive: datetime, zone: ZoneInfo) -> datetime | None:
    """Convert one wall-clock time, or return None when it is ambiguous or skipped."""
    if local_naive.tzinfo is not None:
        local_naive = local_naive.replace(tzinfo=None)
    first = local_naive.replace(tzinfo=zone, fold=0)
    second = local_naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        return None
    utc = first.astimezone(UTC)
    back = utc.astimezone(zone).replace(tzinfo=None)
    if back != local_naive:
        return None
    return utc


def record_meeting_request(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    note: str,
    capture_id: UUID | None = None,
) -> dict:
    if lead.tenant_id != tenant_id or lead.deleted_at is not None:
        return {"status": "not_requested", "meeting_id": "", "blocker": "The lead is not in this workspace."}
    if not _REQUEST.search(note or ""):
        return {"status": "not_requested", "meeting_id": "", "blocker": "A qualified lead has not requested a meeting."}
    plan = _plan(db, tenant_id, lead)
    if plan is None:
        return {"status": "missing_plan", "meeting_id": "", "blocker": "The lead has no operating plan."}
    capture = _capture(db, tenant_id, lead, capture_id, note)
    existing = _existing_request(db, tenant_id, lead.id, capture.id if capture is not None else None, note)
    if existing is not None:
        return {"status": existing.status, "meeting_id": str(existing.id), "blocker": existing.blocker}
    context = build_product_context(db, tenant_id, plan=plan)
    owner = _owner(db, tenant_id, lead)
    row = MeetingRecord(
        tenant_id=tenant_id,
        created_by=actor_id,
        account_id=lead.account_id,
        lead_id=lead.id,
        contact_id=lead.contact_id,
        owner_id=owner.id if owner is not None else None,
        operating_plan_id=plan.id,
        capture_id=capture.id if capture is not None else None,
        title=_title(note, context.customer_facing_name),
        purpose=note.strip()[:500],
        status="meeting_requested",
        provider="google-calendar",
        is_mock=True,
        timezone="UTC",
        context_json=json.dumps(context.as_dict()),
        blocker="" if owner is not None else "Assign an owner before proposing slots.",
        next_steps="Attendance is not recorded.",
    )
    db.add(row)
    db.flush()
    _remember(row, "requested", "A meeting request was recorded.")
    _link_meeting(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, meeting_id=str(row.id))
    return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}


def propose_meet_slots(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    meeting_id: UUID,
    provider: GoogleCalendarProvider | None,
    attendee_timezone: str,
    now: datetime | None = None,
) -> dict:
    row = _meeting(db, tenant_id, meeting_id)
    if row is None:
        return {"status": "missing", "blocker": "The meeting is not in this workspace."}
    blocked = booking_scope_block(db, tenant_id)
    if blocked:
        return _stop(row, blocked)
    if not _explicit_client(provider):
        return _stop(row, NO_LIVE_CALENDAR)
    owner = _owner(db, tenant_id, _lead(db, tenant_id, row))
    if owner is None:
        return _stop(row, "Assign an owner before proposing slots.")
    account = _calendar_account(db, tenant_id, owner.id)
    if isinstance(account, str):
        return _stop(row, account)
    owner_zone = _zone(_owner_timezone(db, tenant_id, actor_id))
    guest_zone = _zone(attendee_timezone)
    if owner_zone is None or guest_zone is None:
        return _stop(row, "The owner or attendee time zone is invalid.")
    moment = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    reading = provider.read_availability(calendar_id=account.provider_account_id or "primary", start=moment, end=moment + _HORIZON)
    if not reading.ok:
        return _stop(row, reading.reason or "Availability is unavailable.")
    slots = _slots(moment, owner_zone, guest_zone, reading.busy)
    row.owner_id = owner.id
    row.provider_connection_id = account.id
    row.calendar_id = account.provider_account_id or "primary"
    row.calendar_account = owner.email
    row.owner_timezone = owner_zone.key
    row.attendee_timezone = guest_zone.key
    row.timezone = owner_zone.key
    row.availability_retrieved_at = reading.retrieved_at
    row.slots_json = json.dumps(slots)
    if not slots:
        return _stop(row, "No open working-hour slot was found. None was invented.")
    row.status = "slots_proposed"
    row.blocker = ""
    row.booking_authorized = False
    _remember(row, "slots_proposed", "Slots were proposed. They are not reserved.")
    db.flush()
    return {"status": row.status, "meeting_id": str(row.id), "slots": slots, "blocker": ""}


def select_meet_slot(
    db: Session,
    *,
    tenant_id: UUID,
    meeting_id: UUID,
    start: str,
    end: str,
) -> dict:
    row = _meeting(db, tenant_id, meeting_id)
    if row is None:
        return {"status": "missing", "blocker": "The meeting is not in this workspace."}
    chosen = next((slot for slot in _stored_slots(row) if slot.get("start") == start and slot.get("end") == end), None)
    if chosen is None:
        return _stop(row, "That time was not one of the proposed slots.")
    row.selected_slot_json = json.dumps(chosen)
    row.start_at = _parse(start)
    row.end_at = _parse(end)
    row.status = "awaiting_authorization"
    row.booking_authorized = False
    row.blocker = ""
    _remember(row, "selected", "A slot was selected. Booking is not authorized.")
    db.flush()
    return {"status": row.status, "meeting_id": str(row.id), "blocker": ""}


def authorize_meet_booking(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    meeting_id: UUID,
    approved: bool,
    invite: bool = False,
) -> dict:
    row = _meeting(db, tenant_id, meeting_id)
    if row is None or row.status != "awaiting_authorization" or not row.selected_slot_json:
        return {"status": "not_authorized", "blocker": "Select a proposed slot before authorizing booking."}
    token = uuid4().hex
    row.operation_token = token
    row.booking_authorized = approved
    row.invite_authorized = bool(approved and invite)
    row.status = "awaiting_authorization" if not approved else "awaiting_authorization"
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="calendar.book",
        title="Book the selected meeting",
        payload_json=json.dumps(
            {
                "meeting_id": str(row.id),
                "operation_token": token,
                "invite": row.invite_authorized,
                "start": json.loads(row.selected_slot_json).get("start"),
                "end": json.loads(row.selected_slot_json).get("end"),
            }
        ),
        status="approved" if approved else "pending",
        entity_type="meeting",
        entity_id=str(row.id),
        idempotency_key=f"calendar.book:{row.id}:{token}",
    )
    db.add(approval)
    db.flush()
    _remember(row, "authorization", "Booking authorization was recorded." if approved else "Booking remains unauthorized.")
    return {"status": approval.status, "approval_id": str(approval.id), "meeting_id": str(row.id), "blocker": ""}


def execute_meet_booking(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    approval: AIApproval,
    provider: GoogleCalendarProvider | None,
    now: datetime | None = None,
) -> dict:
    if approval.tenant_id != tenant_id or approval.action_type != "calendar.book" or approval.status != "approved":
        return {"status": "not_authorized", "blocker": "Booking authorization is missing."}
    payload = _payload(approval)
    row = _meeting(db, tenant_id, _uuid(payload.get("meeting_id") or approval.entity_id))
    if row is None:
        return {"status": "missing", "blocker": "The meeting is not in this workspace."}
    if payload.get("operation_token") != row.operation_token:
        return _stop(row, "This booking job is stale.")
    if row.status == "cancelled":
        return _stop(row, "The meeting is cancelled. It was not created again.")
    blocked = booking_scope_block(db, tenant_id)
    if blocked:
        return _stop(row, blocked)
    if not row.booking_authorized:
        return _stop(row, "A selected slot is not permission to book.")
    if row.provider_event_id and row.status in {"booked", "rescheduled", "cancelled"}:
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    if row.provider_event_id and row.conference_status == "pending":
        if not _explicit_client(provider):
            return {
                "status": row.status,
                "meeting_id": str(row.id),
                "blocker": row.blocker or "The Meet conference is still pending. Another event was not created.",
            }
        return _reconcile_conference(db, tenant_id, actor_id, row, provider)
    if not _explicit_client(provider):
        if row.client_event_id:
            return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker or NO_LIVE_CALENDAR}
        return _stop(row, NO_LIVE_CALENDAR)
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="calendar.meet",
        idempotency_key=f"calendar.meet:{row.id}:create",
        provider="google-calendar",
        approval_id=approval.id,
        entity_type="meeting",
        entity_id=str(row.id),
        request_summary="Create one paused calendar event with a Meet conference.",
    )
    if action.status == "CONFIRMED" and row.provider_event_id:
        if row.conference_status == "pending":
            return _reconcile_conference(db, tenant_id, actor_id, row, provider)
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    if action.status == "UNRESOLVED" or (int(action.attempts or 0) >= 1 and not action.external_id):
        return _reconcile_create(db, tenant_id, actor_id, row, provider, action)
    moment = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    conflict = _recheck(row, provider, moment)
    if conflict:
        return _stop(row, conflict)
    if not row.client_event_id:
        row.client_event_id = uuid4().hex
        row.conference_request_id = f"c{row.client_event_id}"
    row.status = "booking_in_progress"
    action.status = "REQUESTED"
    action.attempts = int(action.attempts or 0) + 1
    db.flush()
    attendees = _attendees(db, tenant_id, row) if row.invite_authorized else []
    result = provider.create_meet_event(
        calendar_id=row.calendar_id or "primary",
        event_id=row.client_event_id,
        request_id=row.conference_request_id,
        title=row.title,
        start=row.start_at,
        end=row.end_at,
        attendees=attendees,
        timezone=row.owner_timezone or row.timezone or "UTC",
        description=row.purpose,
        send_updates="all" if row.invite_authorized else "none",
    )
    return _apply_create(db, tenant_id, actor_id, row, action, result, attendees)


def authorize_meet_change(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    meeting_id: UUID,
    kind: str,
    approved: bool,
    start: str = "",
    end: str = "",
) -> dict:
    row = _meeting(db, tenant_id, meeting_id)
    if row is None or not row.provider_event_id:
        return {"status": "missing", "blocker": "A confirmed calendar event is required."}
    if kind not in {"reschedule", "cancel"}:
        return {"status": "not_authorized", "blocker": "The change is not supported."}
    token = uuid4().hex
    row.operation_token = token
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="calendar.reschedule" if kind == "reschedule" else "calendar.cancel",
        title="Change the booked meeting",
        payload_json=json.dumps(
            {"meeting_id": str(row.id), "operation_token": token, "start": start, "end": end, "kind": kind}
        ),
        status="approved" if approved else "pending",
        entity_type="meeting",
        entity_id=str(row.id),
        idempotency_key=f"calendar.{kind}:{row.id}:{token}",
    )
    db.add(approval)
    db.flush()
    return {"status": approval.status, "approval_id": str(approval.id), "meeting_id": str(row.id)}


def execute_meet_reschedule(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    approval: AIApproval,
    provider: GoogleCalendarProvider | None,
    now: datetime | None = None,
) -> dict:
    return _execute_change(db, tenant_id=tenant_id, actor_id=actor_id, approval=approval, provider=provider, kind="reschedule", now=now)


def execute_meet_cancel(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    approval: AIApproval,
    provider: GoogleCalendarProvider | None,
) -> dict:
    return _execute_change(db, tenant_id=tenant_id, actor_id=actor_id, approval=approval, provider=provider, kind="cancel", now=None)


def meeting_booking_view(db: Session, row: MeetingRecord) -> dict:
    context = _json_dict(row.context_json)
    sources = context.get("sources") if isinstance(context.get("sources"), dict) else {}
    owner = db.get(User, row.owner_id) if row.owner_id is not None else None
    if owner is not None and owner.tenant_id != row.tenant_id:
        owner = None
    fixture = bool(row.is_mock) or row.provider == "mock-calendar"
    join_url = row.join_url or ""
    return {
        "purpose": row.purpose or "",
        "product_name": str(context.get("customer_facing_name") or ""),
        "offer_label": str(sources.get("catalogue_name") or ""),
        "owner_name": owner.name if owner is not None else "",
        "calendar_id": row.calendar_id or "",
        "calendar_account": row.calendar_account or "",
        "owner_timezone": row.owner_timezone or row.timezone or "",
        "attendee_timezone": row.attendee_timezone or "",
        "slots": _stored_slots(row),
        "selected_slot": _json_dict(row.selected_slot_json) if row.selected_slot_json else {},
        "booking_authorized": bool(row.booking_authorized),
        "invite_authorized": bool(row.invite_authorized),
        "conference_status": row.conference_status or "",
        "conference_id": row.conference_id or "",
        "join_url": "" if fixture else join_url,
        "fixture_join_url": join_url if fixture else "",
        "fixture": fixture,
        "blocker": row.blocker or "",
        "availability_retrieved_at": row.availability_retrieved_at,
        "last_synced_at": row.last_synced_at,
        "live_execution_ready": False,
        "attendance": "Attendance is not recorded.",
        "next_action": _next_action(row),
    }


def _execute_change(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    approval: AIApproval,
    provider: GoogleCalendarProvider | None,
    kind: str,
    now: datetime | None,
) -> dict:
    expected = "calendar.reschedule" if kind == "reschedule" else "calendar.cancel"
    if approval.tenant_id != tenant_id or approval.action_type != expected or approval.status != "approved":
        return {"status": "not_authorized", "blocker": "The change is not authorized."}
    payload = _payload(approval)
    row = _meeting(db, tenant_id, _uuid(payload.get("meeting_id") or approval.entity_id))
    if row is None or not row.provider_event_id:
        return {"status": "missing", "blocker": "A confirmed calendar event is required."}
    if payload.get("operation_token") != row.operation_token:
        return {"status": row.status, "meeting_id": str(row.id), "blocker": "This change job is stale."}
    if row.status == "cancelled" and kind == "reschedule":
        return {"status": row.status, "meeting_id": str(row.id), "blocker": "A cancelled meeting was not rescheduled."}
    blocked = booking_scope_block(db, tenant_id)
    if blocked:
        return _stop(row, blocked)
    if not _explicit_client(provider):
        return _stop(row, NO_LIVE_CALENDAR)
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type=f"calendar.meet.{kind}",
        idempotency_key=f"calendar.meet:{row.id}:{kind}:{row.operation_token}",
        provider="google-calendar",
        approval_id=approval.id,
        entity_type="meeting",
        entity_id=str(row.id),
        request_summary=f"{kind} the existing calendar event.",
    )
    if action.status == "CONFIRMED":
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    if action.status == "UNRESOLVED" or int(action.attempts or 0) >= 1:
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker or "The previous change was not repeated."}
    updates = "all" if row.invite_authorized else "none"
    action.attempts = 1
    action.status = "REQUESTED"
    db.flush()
    if kind == "cancel":
        result = provider.cancel_meet(calendar_id=row.calendar_id or "primary", event_id=row.provider_event_id, send_updates=updates)
        if result.unknown:
            action.status = "UNRESOLVED"
            return _stop(row, "Cancellation was not confirmed and was not repeated.")
        if result.http_status == 404 or result.ok:
            previous = row.status
            row.status = "cancelled"
            row.blocker = ""
            row.last_synced_at = datetime.now(UTC)
            confirm_action(action, provider="google-calendar", external_id=row.provider_event_id, response_summary=result.reason)
            _remember(row, "cancelled", result.reason)
            _activity(db, tenant_id, actor_id, row, "Meeting cancelled", result.reason)
            _ = previous
            db.flush()
            return {"status": row.status, "meeting_id": str(row.id), "blocker": ""}
        action.status = "FAILED"
        return _stop(row, result.reason or "Cancellation was refused.")
    start = _parse(str(payload.get("start") or ""))
    end = _parse(str(payload.get("end") or ""))
    if start is None or end is None or end <= start:
        return _stop(row, "The replacement slot is invalid.")
    moment = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    row.start_at = start
    row.end_at = end
    conflict = _recheck(row, provider, moment)
    row.start_at = _parse(_json_dict(row.selected_slot_json).get("start", ""))
    row.end_at = _parse(_json_dict(row.selected_slot_json).get("end", ""))
    if conflict:
        action.status = "FAILED"
        return _stop(row, conflict)
    result = provider.reschedule_meet(
        calendar_id=row.calendar_id or "primary",
        event_id=row.provider_event_id,
        start=start,
        end=end,
        timezone=row.owner_timezone or row.timezone or "UTC",
        send_updates=updates,
    )
    if result.unknown or not result.provider_event_id:
        action.status = "UNRESOLVED"
        return _stop(row, "The reschedule was not confirmed and was not repeated.")
    if result.conference_status == "failure" or not result.join_url:
        action.status = "FAILED"
        row.blocker = result.reason or "The event changed without a usable Meet conference."
        row.status = "needs_review"
        db.flush()
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    row.start_at = start
    row.end_at = end
    row.occurred_at = start
    row.status = "rescheduled"
    row.conference_status = result.conference_status
    row.conference_id = result.conference_id or row.conference_id
    row.join_url = result.join_url
    row.last_synced_at = datetime.now(UTC)
    row.blocker = ""
    row.booking_generation = int(row.booking_generation or 0) + 1
    selected = _json_dict(row.selected_slot_json)
    selected["start"] = start.isoformat()
    selected["end"] = end.isoformat()
    row.selected_slot_json = json.dumps(selected)
    confirm_action(action, provider="google-calendar", external_id=result.provider_event_id, response_summary=result.reason)
    _remember(row, "rescheduled", result.reason)
    _activity(db, tenant_id, actor_id, row, "Meeting rescheduled", result.reason)
    db.flush()
    return {"status": row.status, "meeting_id": str(row.id), "blocker": ""}


def _apply_create(
    db: Session,
    tenant_id: UUID,
    actor_id: UUID,
    row: MeetingRecord,
    action: ProviderAction,
    result: CalendarEventResult,
    attendees: list[str],
) -> dict:
    row.attendees_json = json.dumps(attendees)
    row.last_synced_at = datetime.now(UTC)
    if result.http_status in {401, 403, 429}:
        action.status = "FAILED"
        action.failure_class = "AUTHENTICATION" if result.http_status in {401, 403} else "RATE_LIMIT"
        action.last_error = result.reason
        row.status = "needs_review"
        row.blocker = result.reason
        db.flush()
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    if result.unknown or not result.provider_event_id:
        action.status = "UNRESOLVED"
        action.failure_class = "UNKNOWN"
        action.last_error = result.reason
        row.status = "needs_review"
        row.blocker = "The calendar create is unresolved and was not repeated."
        db.flush()
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    row.provider_event_id = result.provider_event_id
    row.conference_id = result.conference_id
    row.join_url = result.join_url
    row.conference_status = result.conference_status
    row.is_mock = True
    row.provider = "google-calendar"
    if result.conference_status == "pending":
        confirm_action(action, provider="google-calendar", external_id=result.provider_event_id, response_summary=result.reason)
        row.status = "conference_pending"
        row.blocker = result.reason
        _remember(row, "conference_pending", result.reason)
        db.flush()
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    if result.conference_status == "failure" or not result.join_url:
        confirm_action(action, provider="google-calendar", external_id=result.provider_event_id, response_summary=result.reason)
        row.status = "needs_review"
        row.blocker = result.reason or "Meet conference creation failed."
        _remember(row, "conference_failed", row.blocker)
        db.flush()
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    confirm_action(action, provider="google-calendar", external_id=result.provider_event_id, response_summary=result.reason)
    row.status = "booked"
    row.blocker = ""
    row.occurred_at = row.start_at
    lead = _lead(db, tenant_id, row)
    if lead is not None:
        lead.status = "meeting_scheduled"
        _link_meeting(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, meeting_id=str(row.id))
    _remember(row, "booked", "Fixture Google Meet event stored.")
    _activity(db, tenant_id, actor_id, row, "Meeting booked", result.reason)
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="meeting.booked",
        entity_type="meeting",
        entity_id=str(row.id),
        payload={"lead_id": str(row.lead_id or ""), "provider_event_id": row.provider_event_id, "fixture": True},
    )
    db.flush()
    return {"status": row.status, "meeting_id": str(row.id), "blocker": ""}


def _reconcile_create(
    db: Session,
    tenant_id: UUID,
    actor_id: UUID,
    row: MeetingRecord,
    provider: GoogleCalendarProvider,
    action: ProviderAction,
) -> dict:
    if not row.client_event_id:
        action.status = "UNRESOLVED"
        return _stop(row, "The calendar create is unresolved and was not repeated.")
    found = provider.get_event(calendar_id=row.calendar_id or "primary", event_id=row.client_event_id)
    if found.unknown or found.http_status == 404 or not found.provider_event_id:
        action.status = "UNRESOLVED"
        action.failure_class = "UNKNOWN"
        return _stop(row, "The calendar create is unresolved and was not repeated.")
    return _apply_create(db, tenant_id, actor_id, row, action, found, _attendees(db, tenant_id, row) if row.invite_authorized else [])


def _reconcile_conference(
    db: Session,
    tenant_id: UUID,
    actor_id: UUID,
    row: MeetingRecord,
    provider: GoogleCalendarProvider,
) -> dict:
    found = provider.get_event(calendar_id=row.calendar_id or "primary", event_id=row.provider_event_id or "")
    if found.unknown or not found.provider_event_id:
        return _stop(row, "The Meet conference is still unresolved. Another event was not created.")
    if found.conference_status == "pending" or not found.join_url:
        row.conference_status = found.conference_status or "pending"
        row.blocker = "The Meet conference is still pending. Another event was not created."
        row.status = "conference_pending"
        db.flush()
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    if found.conference_status == "failure":
        row.status = "needs_review"
        row.conference_status = "failure"
        row.blocker = found.reason
        db.flush()
        return {"status": row.status, "meeting_id": str(row.id), "blocker": row.blocker}
    row.join_url = found.join_url
    row.conference_id = found.conference_id
    row.conference_status = found.conference_status
    row.status = "booked"
    row.blocker = ""
    row.last_synced_at = datetime.now(UTC)
    lead = _lead(db, tenant_id, row)
    if lead is not None:
        lead.status = "meeting_scheduled"
    _remember(row, "booked", "The pending conference returned a join URL.")
    _ = actor_id
    db.flush()
    return {"status": row.status, "meeting_id": str(row.id), "blocker": ""}


def _recheck(row: MeetingRecord, provider: GoogleCalendarProvider, now: datetime) -> str:
    if row.start_at is None or row.end_at is None:
        return "The selected slot is missing."
    start = _aware(row.start_at)
    end = _aware(row.end_at)
    moment = _aware(now)
    if start < moment + _NOTICE:
        return "The selected slot is inside the minimum notice period."
    reading = provider.read_availability(
        calendar_id=row.calendar_id or "primary",
        start=start - _BUFFER,
        end=end + _BUFFER,
    )
    if not reading.ok or reading.retrieved_at is None:
        return reading.reason or "Availability is unavailable."
    if _overlaps(start - _BUFFER, end + _BUFFER, reading.busy):
        return "The selected slot conflicts with the calendar."
    row.availability_retrieved_at = reading.retrieved_at
    return ""


def _slots(now: datetime, owner_zone: ZoneInfo, guest_zone: ZoneInfo, busy: list[BusyPeriod]) -> list[dict]:
    slots: list[dict] = []
    cursor = now.astimezone(owner_zone).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    horizon = now + _HORIZON
    while len(slots) < 3 and cursor < horizon.astimezone(owner_zone):
        local = cursor.replace(tzinfo=None)
        if cursor.weekday() < 5 and _WORK_START <= local.hour < _WORK_END:
            start = wall_to_utc(local, owner_zone)
            if start is not None:
                end = start + _DURATION
                if start >= now + _NOTICE and not _overlaps(start - _BUFFER, end + _BUFFER, busy):
                    slots.append(
                        {
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                            "owner_timezone": owner_zone.key,
                            "attendee_timezone": guest_zone.key,
                            "owner_local": start.astimezone(owner_zone).strftime("%Y-%m-%d %H:%M"),
                            "attendee_local": start.astimezone(guest_zone).strftime("%Y-%m-%d %H:%M"),
                        }
                    )
        cursor += timedelta(minutes=30)
    return slots


def _overlaps(start: datetime, end: datetime, busy: list[BusyPeriod]) -> bool:
    start = _aware(start)
    end = _aware(end)
    for period in busy:
        if start < _aware(period.end) and end > _aware(period.start):
            return True
    return False


def _explicit_client(provider: GoogleCalendarProvider | None) -> bool:
    return isinstance(provider, GoogleCalendarProvider) and provider.http_post is not None and provider.http_get is not None


def _calendar_account(db: Session, tenant_id: UUID, owner_id: UUID) -> ProviderAccount | str:
    rows = db.scalars(
        select(ProviderAccount).where(
            ProviderAccount.tenant_id == tenant_id,
            ProviderAccount.provider == "google",
            ProviderAccount.connected_user_id == owner_id,
            ProviderAccount.deleted_at.is_(None),
        )
    ).all()
    connected = [row for row in rows if row.status == "connected"]
    if any(row.status == "revoked" for row in rows) and not connected:
        return "The calendar connection is revoked."
    if len(connected) != 1:
        return "The calendar connection is missing or ambiguous."
    account = connected[0]
    if not has_scopes(account, [_EVENTS_SCOPE]) or not any(has_scopes(account, [scope]) for scope in _READ_SCOPES):
        return "The calendar connection cannot read availability and create events."
    if not (account.provider_account_id or "").strip():
        return "The target calendar is missing."
    return account


def _owner(db: Session, tenant_id: UUID, lead: Lead | None) -> User | None:
    if lead is None or lead.owner_id is None:
        return None
    owner = db.get(User, lead.owner_id)
    if owner is None or owner.tenant_id != tenant_id or not owner.is_active:
        return None
    return owner


def _plan(db: Session, tenant_id: UUID, lead: Lead) -> OperatingPlan | None:
    if lead.operating_plan_id is None:
        return None
    plan = db.get(OperatingPlan, lead.operating_plan_id)
    if plan is None or plan.tenant_id != tenant_id or plan.deleted_at is not None or plan.product_id is None:
        return None
    return plan


def _capture(db: Session, tenant_id: UUID, lead: Lead, capture_id: UUID | None, note: str) -> InboundCapture | None:
    if capture_id is not None:
        row = db.get(InboundCapture, capture_id)
        if row is None or row.tenant_id != tenant_id or row.lead_id != lead.id or row.deleted_at is not None:
            return None
        return row
    rows = db.scalars(
        select(InboundCapture)
        .where(
            InboundCapture.tenant_id == tenant_id,
            InboundCapture.lead_id == lead.id,
            InboundCapture.deleted_at.is_(None),
        )
        .order_by(InboundCapture.created_at.desc())
    ).all()
    for row in rows:
        if note.strip() and note.strip() in (row.request_note or ""):
            return row
    return None


def _existing_request(db: Session, tenant_id: UUID, lead_id: UUID, capture_id: UUID | None, note: str) -> MeetingRecord | None:
    stmt = select(MeetingRecord).where(
        MeetingRecord.tenant_id == tenant_id,
        MeetingRecord.lead_id == lead_id,
        MeetingRecord.deleted_at.is_(None),
        MeetingRecord.status != "cancelled",
    )
    if capture_id is not None:
        stmt = stmt.where(MeetingRecord.capture_id == capture_id)
    else:
        stmt = stmt.where(MeetingRecord.purpose == note.strip()[:500])
    return db.scalar(stmt.order_by(MeetingRecord.created_at.asc()))


def _meeting(db: Session, tenant_id: UUID, meeting_id: UUID | str | None) -> MeetingRecord | None:
    parsed = meeting_id if isinstance(meeting_id, UUID) else _uuid(meeting_id)
    if parsed is None:
        return None
    row = db.get(MeetingRecord, parsed)
    if row is None or row.tenant_id != tenant_id or row.deleted_at is not None:
        return None
    return row


def _lead(db: Session, tenant_id: UUID, row: MeetingRecord) -> Lead | None:
    if row.lead_id is None:
        return None
    lead = db.get(Lead, row.lead_id)
    if lead is None or lead.tenant_id != tenant_id or lead.deleted_at is not None:
        return None
    return lead


def _attendees(db: Session, tenant_id: UUID, row: MeetingRecord) -> list[str]:
    lead = _lead(db, tenant_id, row)
    owner = db.get(User, row.owner_id) if row.owner_id is not None else None
    emails = []
    if lead is not None and lead.email:
        emails.append(lead.email)
    if owner is not None and owner.tenant_id == tenant_id and owner.email and owner.email not in emails:
        emails.append(owner.email)
    return emails


def _owner_timezone(db: Session, tenant_id: UUID, actor_id: UUID) -> str:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    return settings.timezone or ""


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return None


def _stored_slots(row: MeetingRecord) -> list[dict]:
    data = _json_list(row.slots_json)
    return [item for item in data if isinstance(item, dict)]


def _json_dict(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_list(raw: str) -> list:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _payload(approval: AIApproval) -> dict:
    return _json_dict(approval.payload_json)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _title(note: str, product: str) -> str:
    _ = note
    label = product or "product"
    return f"Meet about {label}"[:200]


def _stop(row: MeetingRecord, blocker: str) -> dict:
    if row.status not in {"booked", "rescheduled", "cancelled", "conference_pending"}:
        row.status = "needs_review" if row.status not in {"meeting_requested", "slots_proposed", "awaiting_authorization"} else row.status
    if row.status in {"meeting_requested", "slots_proposed", "awaiting_authorization", "booking_in_progress"} and blocker:
        row.status = "needs_review" if "unavailable" in blocker.lower() or "conflict" in blocker.lower() or "unresolved" in blocker.lower() else row.status
    row.blocker = blocker
    return {"status": row.status, "meeting_id": str(row.id), "blocker": blocker}


def _remember(row: MeetingRecord, action: str, detail: str) -> None:
    data = _json_dict(row.insights_json)
    history = data.get("booking_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "action": action,
            "at": datetime.now(UTC).isoformat(),
            "status": row.status,
            "event_id": row.provider_event_id or "",
            "conference_id": row.conference_id or "",
            "start": row.start_at.isoformat() if row.start_at is not None else "",
            "end": row.end_at.isoformat() if row.end_at is not None else "",
            "detail": detail,
        }
    )
    data["booking_history"] = history
    row.insights_json = json.dumps(data)


def _activity(db: Session, tenant_id: UUID, actor_id: UUID, row: MeetingRecord, title: str, body: str) -> None:
    if row.lead_id is None:
        return
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(row.lead_id),
        activity_type="meeting",
        title=title,
        body=body,
        actor_type="ai",
    )


def _next_action(row: MeetingRecord) -> str:
    if row.blocker:
        return row.blocker
    if row.status == "meeting_requested":
        return "Propose slots from the owner's calendar."
    if row.status == "slots_proposed":
        return "Select a proposed slot."
    if row.status == "awaiting_authorization" and row.booking_authorized:
        return "Booking is authorized and has not been created."
    if row.status == "awaiting_authorization":
        return "Authorize booking before an event is created."
    if row.status == "conference_pending":
        return "Read the event again. Do not create another event."
    if row.status == "booked":
        return "The fixture event is booked. Attendance is not recorded."
    if row.status == "rescheduled":
        return "The replacement time was confirmed. Attendance is not recorded."
    if row.status == "cancelled":
        return "The cancellation was confirmed."
    if row.status == "needs_review":
        return "Review the booking blocker."
    return "No booking is in progress."
