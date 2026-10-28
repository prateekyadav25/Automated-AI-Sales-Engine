import json
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.runtime import meeting_prep
from app.core.config import get_settings
from app.models.ai import AIApproval, AIRecommendation
from app.models.crm import Account, Lead, Opportunity
from app.models.execution import JourneyLink
from app.models.identity import User
from app.models.lifecycle import MeetingRecord
from app.providers.calendar import NO_LIVE_CALENDAR, BusyPeriod, get_calendar_provider
from app.services.audit import emit_event
from app.services.automation_state import upsert_state
from app.services.autopilot_settings import get_or_create_settings
from app.services.crm import add_activity
from app.services.demo_guard import external_execution_block
from app.services.nba import generate_for_lead
from app.services.rbac import user_permissions


def select_meeting_owner(db: Session, *, tenant_id: UUID, lead: Lead) -> User | None:
    if lead.account_id:
        opportunity = db.scalar(
            select(Opportunity)
            .where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.account_id == lead.account_id,
                Opportunity.deleted_at.is_(None),
                Opportunity.owner_id.is_not(None),
            )
            .order_by(Opportunity.created_at.desc())
        )
        if opportunity and opportunity.owner_id:
            owner = db.scalar(select(User).where(User.id == opportunity.owner_id, User.tenant_id == tenant_id, User.is_active.is_(True)))
            if owner is not None:
                return owner
        account = db.scalar(select(Account).where(Account.tenant_id == tenant_id, Account.id == lead.account_id))
        if account and account.created_by:
            owner = db.scalar(select(User).where(User.id == account.created_by, User.tenant_id == tenant_id, User.is_active.is_(True)))
            if owner is not None:
                return owner
    users = db.scalars(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)).order_by(User.created_at.asc())).all()
    for user in users:
        if "meetings.write" in user_permissions(db, user):
            return user
    return None


def _overlaps(start: datetime, end: datetime, busy: list[BusyPeriod]) -> bool:
    for period in busy:
        if start < period.end and end > period.start:
            return True
    return False


def propose_slots(
    db: Session,
    *,
    tenant_id: UUID,
    timezone: str = "UTC",
    duration_minutes: int = 30,
    count: int = 3,
) -> list[dict]:
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
        timezone = "UTC"
    now = datetime.now(UTC)
    window_end = now + timedelta(days=7)
    provider = get_calendar_provider(db, tenant_id)
    reader = getattr(provider, "read_availability", None)
    if reader is not None:
        reading = reader(calendar_id="primary", start=now, end=window_end)
        if not reading.ok:
            return []
        busy = reading.busy
    elif not provider.health().connected:
        return []
    else:
        busy = provider.get_availability(calendar_id="primary", start=now, end=window_end)
    slots: list[dict] = []
    cursor = now.astimezone(zone).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while len(slots) < count and cursor < window_end.astimezone(zone):
        if cursor.weekday() < 5 and 9 <= cursor.hour < 17:
            start = cursor.astimezone(UTC)
            end = start + timedelta(minutes=duration_minutes)
            if start > now and not _overlaps(start, end, busy):
                slots.append({"start": start.isoformat(), "end": end.isoformat(), "timezone": timezone})
        cursor += timedelta(minutes=30)
    return slots


def meeting_by_event(db: Session, tenant_id: UUID, provider: str, provider_event_id: str) -> MeetingRecord | None:
    return db.scalar(
        select(MeetingRecord).where(
            MeetingRecord.tenant_id == tenant_id,
            MeetingRecord.provider == provider,
            MeetingRecord.provider_event_id == provider_event_id,
            MeetingRecord.deleted_at.is_(None),
        )
    )


def book_meeting(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    approval: AIApproval,
    payload: dict,
) -> str:
    lead_id = payload.get("lead_id") or approval.entity_id
    if not lead_id:
        return "Meeting was not booked: lead is missing."
    lead = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.id == UUID(str(lead_id)), Lead.deleted_at.is_(None)))
    if lead is None:
        return "Meeting was not booked: lead is missing."
    owner = select_meeting_owner(db, tenant_id=tenant_id, lead=lead)
    if owner is None:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="meeting_owner_missing",
            next_action="assign_owner",
            blocked_reason="BLOCKED BY CONFIGURATION",
            run_id=approval.run_id,
        )
        return "BLOCKED BY CONFIGURATION"
    start_raw = payload.get("start_at")
    end_raw = payload.get("end_at")
    timezone = str(payload.get("timezone") or "UTC")
    if not start_raw or not end_raw:
        return "Meeting was not booked: start_at and end_at are required."
    start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
    blocked = external_execution_block(db, tenant_id=tenant_id, action="calendar.book", recipient=lead.email or "")
    if blocked:
        return blocked
    if (get_settings().calendar_provider or "").strip().lower() == "google":
        return NO_LIVE_CALENDAR
    provider = get_calendar_provider(db, tenant_id)
    health = provider.health()
    if not health.connected:
        return "BLOCKED BY CONFIGURATION"
    existing_id = str(payload.get("provider_event_id") or "")
    if existing_id:
        existing = meeting_by_event(db, tenant_id, health.provider, existing_id)
        if existing is not None:
            return f"Provider {existing.provider} already booked {existing.provider_event_id}."
    result = provider.create_event(
        title=str(payload.get("title") or f"Meeting with {lead.email}"),
        start=start,
        end=end,
        attendees=[lead.email],
        timezone=timezone,
        description=str(payload.get("description") or ""),
    )
    if not result.ok:
        return result.reason or "Calendar create failed."
    duplicate = meeting_by_event(db, tenant_id, result.provider, result.provider_event_id)
    if duplicate is not None:
        return f"Provider {duplicate.provider} already booked {duplicate.provider_event_id}."
    attendees = [address for address in [lead.email, owner.email] if address]
    row = MeetingRecord(
        tenant_id=tenant_id,
        created_by=actor_id,
        account_id=lead.account_id,
        lead_id=lead.id,
        contact_id=lead.contact_id,
        owner_id=owner.id,
        title=str(payload.get("title") or f"Meeting with {lead.email}"),
        occurred_at=start,
        start_at=start,
        end_at=end,
        timezone=timezone,
        status="booked",
        provider=result.provider,
        is_mock=result.is_mock,
        provider_event_id=result.provider_event_id,
        calendar_account=owner.email,
        summary=str(payload.get("summary") or ""),
        next_steps="Prepare for the meeting.",
        insights_json=json.dumps({"attendees": attendees}),
    )
    db.add(row)
    db.flush()
    _link_meeting(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, meeting_id=str(row.id))
    lead.status = "meeting_scheduled"
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="meeting",
        title="Meeting booked",
        body=f"{result.reason} event={result.provider_event_id}",
        actor_type="ai",
    )
    upsert_state(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        state="MEETING_SCHEDULED",
        last_action="meeting_booked",
        next_action="prepare_meeting",
        blocked_reason="",
        run_id=approval.run_id,
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="meeting.booked",
        entity_type="lead",
        entity_id=str(lead.id),
        payload={"meeting_id": str(row.id), "provider_event_id": result.provider_event_id, "provider": result.provider},
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="meeting.created",
        entity_type="meeting",
        entity_id=str(row.id),
        payload={"lead_id": str(lead.id)},
    )
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    if settings.meeting_preparation_enabled and lead.account_id:
        user = db.get(User, actor_id)
        meeting_prep(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            permissions=user_permissions(db, user) if user else set(),
            account_id=lead.account_id,
            commit=False,
        )
    generate_for_lead(db, tenant_id, lead, actor_id)
    db.flush()
    return f"Provider {result.provider} booked {result.provider_event_id}."


def reschedule_meeting(db: Session, *, tenant_id: UUID, actor_id: UUID, approval: AIApproval, payload: dict) -> str:
    meeting_id = payload.get("meeting_id")
    if not meeting_id:
        return "Meeting was not rescheduled: meeting_id is missing."
    row = db.scalar(
        select(MeetingRecord).where(
            MeetingRecord.tenant_id == tenant_id,
            MeetingRecord.id == UUID(str(meeting_id)),
            MeetingRecord.deleted_at.is_(None),
        )
    )
    if row is None or not row.provider_event_id:
        return "Meeting was not rescheduled: booked event is missing."
    start = datetime.fromisoformat(str(payload["start_at"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(payload["end_at"]).replace("Z", "+00:00"))
    timezone = str(payload.get("timezone") or row.timezone or "UTC")
    provider = get_calendar_provider(db, tenant_id)
    result = provider.reschedule(provider_event_id=row.provider_event_id, start=start, end=end, timezone=timezone)
    if not result.ok:
        return result.reason or "Reschedule failed."
    row.start_at = start
    row.end_at = end
    row.occurred_at = start
    row.timezone = timezone
    row.status = "rescheduled"
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(row.lead_id or approval.entity_id),
        activity_type="meeting",
        title="Meeting rescheduled",
        body=result.reason,
        actor_type="ai",
    )
    return f"Provider {result.provider} rescheduled {row.provider_event_id}."


def cancel_meeting(db: Session, *, tenant_id: UUID, actor_id: UUID, approval: AIApproval, payload: dict) -> str:
    meeting_id = payload.get("meeting_id")
    if not meeting_id:
        return "Meeting was not cancelled: meeting_id is missing."
    row = db.scalar(
        select(MeetingRecord).where(
            MeetingRecord.tenant_id == tenant_id,
            MeetingRecord.id == UUID(str(meeting_id)),
            MeetingRecord.deleted_at.is_(None),
        )
    )
    if row is None or not row.provider_event_id:
        return "Meeting was not cancelled: booked event is missing."
    provider = get_calendar_provider(db, tenant_id)
    result = provider.cancel(provider_event_id=row.provider_event_id)
    if not result.ok:
        return result.reason or "Cancel failed."
    row.status = "cancelled"
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(row.lead_id or approval.entity_id),
        activity_type="meeting",
        title="Meeting cancelled",
        body=result.reason,
        actor_type="ai",
    )
    return f"Provider {result.provider} cancelled {row.provider_event_id}."


def offer_discovery_meeting(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    run_id: UUID | None = None,
) -> dict:
    provider = get_calendar_provider(db, tenant_id)
    health = provider.health()
    if not health.connected:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="WAITING_FOR_CONFIGURATION",
            last_action="meeting_offer",
            next_action="connect_calendar",
            blocked_reason=health.reason,
            run_id=run_id,
        )
        return {"status": "waiting_for_configuration", "waiting_reason": health.reason, "slots": []}
    approval = queue_meeting_proposal(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, run_id=run_id)
    if approval is None:
        return {"status": "waiting", "waiting_reason": "No open working-hour slots on the connected calendar.", "slots": []}
    payload = json.loads(approval.payload_json or "{}")
    return {"status": "proposed", "approval_id": str(approval.id), "slots": payload.get("slots") or [], "waiting_reason": ""}


def confirm_discovery_slot(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    start_at: str,
    end_at: str,
    timezone: str = "UTC",
) -> dict:
    approval = db.scalar(
        select(AIApproval)
        .where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.entity_id == str(lead.id),
            AIApproval.idempotency_key.like("calendar.propose:%"),
            AIApproval.deleted_at.is_(None),
        )
        .order_by(AIApproval.created_at.desc())
    )
    if approval is None:
        return {"status": "missing_offer", "detail": "Offer calendar slots before confirming one."}
    payload = json.loads(approval.payload_json or "{}")
    slots = payload.get("slots") or []
    chosen = next((slot for slot in slots if slot.get("start") == start_at and slot.get("end") == end_at), None)
    if chosen is None:
        return {"status": "rejected", "detail": "That time was not one of the offered slots."}
    provider = get_calendar_provider(db, tenant_id)
    if not provider.health().connected:
        return {"status": "waiting_for_configuration", "detail": provider.health().reason}
    booking = {
        **payload,
        "start_at": start_at,
        "end_at": end_at,
        "timezone": timezone or chosen.get("timezone") or "UTC",
        "title": f"Discovery meeting with {lead.email or lead.company_name}",
    }
    note = book_meeting(db, tenant_id=tenant_id, actor_id=actor_id, approval=approval, payload=booking)
    if not note.startswith("Provider"):
        return {"status": "not_booked", "detail": note}
    meeting = db.scalar(
        select(MeetingRecord)
        .where(MeetingRecord.tenant_id == tenant_id, MeetingRecord.lead_id == lead.id, MeetingRecord.deleted_at.is_(None))
        .order_by(MeetingRecord.created_at.desc())
    )
    return {
        "status": "booked",
        "detail": note,
        "meeting_id": str(meeting.id) if meeting is not None else "",
        "provider_event_id": meeting.provider_event_id if meeting is not None else "",
    }


def reschedule_booked_meeting(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    meeting_id: UUID,
    start_at: str,
    end_at: str,
    timezone: str = "",
) -> str:
    approval = AIApproval(tenant_id=tenant_id, created_by=actor_id, action_type="calendar.reschedule", title="Reschedule", payload_json="{}", status="approved")
    return reschedule_meeting(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        approval=approval,
        payload={"meeting_id": str(meeting_id), "start_at": start_at, "end_at": end_at, "timezone": timezone},
    )


def cancel_booked_meeting(db: Session, *, tenant_id: UUID, actor_id: UUID, meeting_id: UUID) -> str:
    approval = AIApproval(tenant_id=tenant_id, created_by=actor_id, action_type="calendar.cancel", title="Cancel", payload_json="{}", status="approved")
    return cancel_meeting(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        approval=approval,
        payload={"meeting_id": str(meeting_id)},
    )


def _link_meeting(db: Session, *, tenant_id: UUID, actor_id: UUID, lead: Lead, meeting_id: str) -> None:
    journey_key = f"lead:{lead.id}"
    existing = db.scalar(
        select(JourneyLink.id).where(
            JourneyLink.tenant_id == tenant_id,
            JourneyLink.journey_key == journey_key,
            JourneyLink.entity_type == "meeting",
            JourneyLink.entity_id == meeting_id,
            JourneyLink.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return
    db.add(
        JourneyLink(
            tenant_id=tenant_id,
            created_by=actor_id,
            journey_key=journey_key,
            entity_type="meeting",
            entity_id=meeting_id,
            role="discovery",
        )
    )


def queue_meeting_proposal(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    run_id: UUID | None = None,
) -> AIApproval | None:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    slots = propose_slots(db, tenant_id=tenant_id, timezone=settings.timezone)
    if not slots:
        db.add(
            AIRecommendation(
                tenant_id=tenant_id,
                created_by=actor_id,
                entity_type="lead",
                entity_id=str(lead.id),
                kind="calendar",
                title="No meeting slots available",
                body="Availability math found no open working-hour slots.",
                status="draft",
            )
        )
        return None
    key = f"calendar.propose:{lead.id}:{slots[0]['start']}"
    exists = db.scalar(
        select(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.idempotency_key == key,
            AIApproval.deleted_at.is_(None),
        )
    )
    if exists is not None:
        return exists
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="email.send",
        title=f"Propose meeting times to {lead.email}",
        payload_json=json.dumps(
            {
                "lead_id": str(lead.id),
                "subject": "Proposed times to meet",
                "body": "Here are times that work on our side:\n" + "\n".join(f"- {slot['start']} to {slot['end']}" for slot in slots),
                "slots": slots,
                "why": "Reply asked for a meeting. Slots are computed from calendar busy times.",
                "evidence": "Deterministic availability, not an LLM guess.",
                "risk": "External email.",
                "expected_outcome": "Prospect picks a slot; booking stays on a later approval.",
            }
        ),
        status="pending",
        run_id=run_id,
        entity_type="lead",
        entity_id=str(lead.id),
        idempotency_key=key,
    )
    db.add(approval)
    db.flush()
    return approval
