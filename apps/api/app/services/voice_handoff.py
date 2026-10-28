"""Permissioned callback on the existing call, approval, and meeting path.

Twilio Programmable Voice, Calls API 2010-04-01, is the only provider used
here. The client must be injected. This module does not construct httpx, does
not register a status callback, does not record, and does not bridge a call.
A qualified lead, a phone number, email consent, or a saved task is not
permission to dial. A completed call is not a useful conversation or a sale.

Call create has no documented idempotency key. An unknown result is stored
and is not posted again. A stored Call SID can be read back. Status events
use CallStatus and SequenceNumber. The signature is HMAC-SHA1 of the callback
URL plus the sorted form fields, using the connection token. A tenant id in
the payload is ignored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.acquisition import InboundCapture
from app.models.ai import AIApproval
from app.models.crm import Contact, Lead, Task
from app.models.execution import JourneyLink
from app.models.funnel import VoiceSession
from app.models.identity import User
from app.models.integrations import ProviderAccount
from app.models.lifecycle import Conversation
from app.providers.voice_telephony import NO_LIVE_VOICE, TwilioCallClient
from app.services.audit import emit_event
from app.services.autopilot_settings import get_or_create_settings, in_quiet_hours
from app.services.crm import add_activity
from app.services.demo_guard import EXPIRED_BLOCK, PREPARED_BLOCK, _operating_mode, _scope_expired, scope_for_execution
from app.services.meet_booking import record_meeting_request
from app.services.product_context import context_for_lead
from app.services.provider_ops import begin_action, confirm_action

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_ACCOUNT_SID = re.compile(r"^AC[0-9a-fA-F]{32}$")
_CALLBACK = re.compile(r"\b(call me|callback|call back|phone me|ring me)\b", re.IGNORECASE)
_HUMAN = re.compile(r"\b(transfer me|speak to a person|talk to a human|human agent)\b", re.IGNORECASE)
_INJECTION = re.compile(
    r"\b(ignore previous|disregard|you are now|system prompt|authorize spend|mark the deal won|grant permission|grant call permission)\b",
    re.IGNORECASE,
)
_ALLOWED_SCOPE = {"callback", "stated_purpose"}
_TERMINAL = {"completed", "busy", "no_answer", "failed", "cancelled"}
_STATUS = {
    "queued": "queued",
    "initiated": "initiated",
    "ringing": "ringing",
    "in-progress": "answered",
    "answered": "answered",
    "completed": "completed",
    "busy": "busy",
    "failed": "failed",
    "no-answer": "no_answer",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}
_MISSING_SCOPE = "Voice stays outside this demonstration. No call was placed."
_TWIML = "<Response><Say>This is a requested callback.</Say></Response>"


def voice_scope_block(db: Session, tenant_id: UUID) -> str:
    scope = scope_for_execution(db, tenant_id)
    if scope is not None and _scope_expired(scope):
        return EXPIRED_BLOCK
    if scope is not None and scope.status == "prepared":
        return PREPARED_BLOCK
    if scope is not None:
        return "Voice stays outside this demonstration. No call was placed."
    if _operating_mode(db, tenant_id) == "DEMO":
        return _MISSING_SCOPE
    return ""


def record_callback_request(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead_id: UUID,
    note: str,
    capture_id: UUID | None = None,
    window_start: str = "",
    window_end: str = "",
) -> dict:
    lead = _lead(db, tenant_id, lead_id)
    if lead is None:
        return _denied("The lead is not in this workspace.")
    if not _CALLBACK.search(note or ""):
        return _denied("A callback has not been requested. A qualified lead is not permission to call.")
    start, end, window_error = _parse_window(window_start, window_end)
    if window_error:
        return _denied(window_error)
    purpose = " ".join((note or "").split())
    return _open_session(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        lead=lead,
        capture_id=capture_id,
        purpose=purpose,
        evidence={
            "source": "callback_request",
            "evidenced_at": datetime.now(UTC).isoformat(),
            "channel": "request",
            "purpose": purpose,
            "scope": "callback",
            "window_start": start.isoformat() if start else "",
            "window_end": end.isoformat() if end else "",
        },
        window_start=start,
        window_end=end,
    )


def record_call_permission(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead_id: UUID,
    source: str,
    channel: str,
    purpose: str,
    scope: str,
    evidenced_at: str,
    capture_id: UUID | None = None,
) -> dict:
    lead = _lead(db, tenant_id, lead_id)
    if lead is None:
        return _denied("The lead is not in this workspace.")
    clean_purpose = " ".join((purpose or "").split())
    clean_scope = (scope or "").strip().lower()
    clean_channel = (channel or "").strip().lower()
    if not clean_purpose or not (source or "").strip() or not clean_channel or not (evidenced_at or "").strip():
        return _denied("Call permission needs a source, time, channel, purpose, and scope.")
    if clean_scope not in _ALLOWED_SCOPE:
        return _denied("This permission does not authorize a marketing call.")
    if clean_channel == "email":
        stored = _open_session(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            capture_id=capture_id,
            purpose=clean_purpose,
            evidence={
                "source": source.strip(),
                "evidenced_at": evidenced_at.strip(),
                "channel": "email",
                "purpose": clean_purpose,
                "scope": clean_scope,
            },
            window_start=None,
            window_end=None,
        )
        if stored.get("session_id"):
            row = _session(db, tenant_id, _uuid(stored["session_id"]))
            if row is not None:
                row.blocker = "Email permission does not authorize a call."
        return {**stored, "blocker": "Email permission does not authorize a call."}
    return _open_session(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        lead=lead,
        capture_id=capture_id,
        purpose=clean_purpose,
        evidence={
            "source": source.strip(),
            "evidenced_at": evidenced_at.strip(),
            "channel": clean_channel,
            "purpose": clean_purpose,
            "scope": clean_scope,
        },
        window_start=None,
        window_end=None,
    )


def authorize_voice_attempt(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    session_id: UUID,
    approved: bool,
    recording: bool = False,
    now: datetime | None = None,
) -> dict:
    row = _session(db, tenant_id, session_id)
    if row is None:
        return _denied("The call is not in this workspace.")
    blocked = voice_scope_block(db, tenant_id)
    if blocked:
        row.call_authorized = False
        row.blocker = blocked
        row.status = "review"
        return {"status": row.status, "session_id": str(row.id), "approval_id": "", "blocker": blocked}
    row.recording_authorized = bool(recording)
    blocker = _execution_blocker(db, tenant_id, actor_id, row, now)
    if recording:
        blocker = blocker or "Recording policy is not configured. The call was not placed."
    if blocker or not approved:
        row.call_authorized = False
        row.blocker = blocker or "The call attempt was not approved."
        row.status = "review"
        return {"status": row.status, "session_id": str(row.id), "approval_id": "", "blocker": row.blocker}
    token = uuid4().hex
    row.operation_token = token
    row.call_authorized = True
    row.status = "authorized"
    row.blocker = ""
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="voice.handoff",
        title="Place the requested callback",
        payload_json=json.dumps({"session_id": str(row.id), "operation_token": token}),
        status="approved",
        entity_type="voice_session",
        entity_id=str(row.id),
        idempotency_key=f"voice.handoff:{row.id}:{token}",
    )
    db.add(approval)
    db.flush()
    row.approval_id = approval.id
    return {"status": approval.status, "session_id": str(row.id), "approval_id": str(approval.id), "blocker": ""}


def execute_voice_handoff(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    approval: AIApproval,
    client: TwilioCallClient | None,
    now: datetime | None = None,
) -> dict:
    if approval.tenant_id != tenant_id or approval.action_type != "voice.handoff" or approval.status != "approved":
        return _denied("The call attempt is not authorized.")
    payload = _json_dict(approval.payload_json)
    row = _session(db, tenant_id, _uuid(payload.get("session_id") or approval.entity_id))
    if row is None:
        return _denied("The call is not in this workspace.")
    if payload.get("operation_token") != row.operation_token:
        return _stop(row, "This call job is stale.")
    if row.status == "cancelled":
        return _stop(row, "The call is cancelled. It was not placed again.")
    blocked = voice_scope_block(db, tenant_id)
    if blocked:
        return _stop(row, blocked)
    if not row.call_authorized:
        return _stop(row, "A saved call task does not authorize a call.")
    if row.recording_authorized:
        return _stop(row, "Recording policy is not configured. The call was not placed.")
    blocker = _execution_blocker(db, tenant_id, actor_id, row, now)
    if blocker:
        return _stop(row, blocker)
    if row.provider_call_id:
        return _reconcile_known(db, row, client)
    if client is None:
        return _stop(row, NO_LIVE_VOICE)
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="voice.handoff",
        idempotency_key=f"voice.handoff:{row.id}:create",
        provider="twilio",
        approval_id=approval.id,
        entity_type="voice_session",
        entity_id=str(row.id),
        request_summary="Place one requested callback.",
    )
    if action.status == "CONFIRMED" and row.provider_call_id:
        return _view_state(row)
    if action.status == "UNRESOLVED" or (int(action.attempts or 0) >= 1 and not action.external_id):
        return _reconcile_unknown(db, row, client, action)
    fresh = _execution_blocker(db, tenant_id, actor_id, row, now)
    if fresh:
        return _stop(row, fresh)
    action.attempts = int(action.attempts or 0) + 1
    action.status = "REQUESTED"
    row.attempt_count = 1
    db.flush()
    try:
        status, payload = client.create_call(
            to_number=row.recipient_e164,
            from_number=row.caller_identity,
            twiml=_TWIML,
        )
    except Exception:
        action.status = "UNRESOLVED"
        row.status = "unresolved"
        return _stop(row, "The call create did not return a result. It was not repeated.")
    return _apply_create(db, tenant_id, actor_id, row, action, status, payload)


def accept_twilio_callback(db: Session, *, url: str, params: dict[str, str], signature: str | None) -> dict:
    """Verify the connection token, persist the event, then acknowledge it."""
    call_sid = (params.get("CallSid") or "").strip()
    if not call_sid:
        return {"status": "rejected", "blocker": "The callback has no call id."}
    matches = db.scalars(
        select(VoiceSession).where(VoiceSession.provider_call_id == call_sid, VoiceSession.deleted_at.is_(None))
    ).all()
    if len(matches) != 1:
        return {"status": "unknown", "blocker": "The call id is not a stored attempt."}
    row = matches[0]
    account = db.get(ProviderAccount, row.provider_connection_id) if row.provider_connection_id else None
    token = str(_config(account).get("auth_token") or "") if account is not None and account.tenant_id == row.tenant_id else ""
    if not token or not signature or not hmac.compare_digest(_twilio_signature(url, params, token), signature):
        return {"status": "invalid_signature", "blocker": "The callback signature was rejected."}
    sequence = _sequence(params.get("SequenceNumber"))
    raw_status = (params.get("CallStatus") or "").strip().lower()
    mapped = _STATUS.get(raw_status, "unknown")
    events = _events(row)
    if any(item.get("sequence") == sequence and item.get("raw_status") == raw_status for item in events if sequence is not None):
        return {"status": row.status, "session_id": str(row.id), "blocker": "The callback was already stored."}
    applied = sequence is None or row.last_sequence < 0 or sequence >= row.last_sequence
    if raw_status and mapped == "unknown":
        applied = False
    if row.status in _TERMINAL and (sequence is None or sequence < row.last_sequence):
        applied = False
    events.append(
        {
            "sequence": sequence,
            "status": mapped,
            "raw_status": raw_status,
            "applied": applied,
            "at": datetime.now(UTC).isoformat(),
        }
    )
    row.events_json = json.dumps(events)
    db.flush()
    if applied:
        row.status = mapped
        row.last_event = mapped
        row.last_sequence = sequence if sequence is not None else row.last_sequence
        if mapped == "completed":
            row.outcome = "completed"
        elif mapped in _TERMINAL:
            row.outcome = mapped
        if mapped in {"busy", "no_answer"}:
            row.blocker = "The call was not answered. No retry is configured."
        elif mapped == "failed":
            row.blocker = "The provider reported a failed call. It was not repeated."
        elif mapped == "cancelled":
            row.blocker = "The provider reported the call as cancelled."
        elif mapped == "completed":
            row.blocker = ""
    conversation = db.get(Conversation, row.conversation_id) if row.conversation_id else None
    if conversation is not None and conversation.tenant_id == row.tenant_id:
        conversation.call_status = row.status
        if row.outcome:
            conversation.outcome = row.outcome
    return {"status": row.status, "session_id": str(row.id), "tenant_id": str(row.tenant_id), "blocker": row.blocker}


def apply_voice_transcript(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    session_id: UUID,
    transcript: str,
) -> dict:
    row = _session(db, tenant_id, session_id)
    if row is None:
        return _denied("The call is not in this workspace.")
    text = (transcript or "").strip()
    conversation = db.get(Conversation, row.conversation_id) if row.conversation_id else None
    if conversation is not None and conversation.tenant_id == tenant_id:
        conversation.transcript = text
        conversation.summary = ""
    if not text:
        return {"status": row.status, "session_id": str(row.id), "blocker": "No transcript is stored."}
    if _INJECTION.search(text):
        row.blocker = "The transcript was stored as untrusted text and did not authorize an action."
        return {"status": row.status, "session_id": str(row.id), "blocker": row.blocker}
    if _HUMAN.search(text):
        _handoff(db, tenant_id, actor_id, row)
    lead = _lead(db, tenant_id, row.lead_id)
    if lead is not None and re.search(r"\b(meet|meeting|schedule a call|book a time)\b", text, re.IGNORECASE):
        if row.meeting_id is None:
            result = record_meeting_request(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                lead=lead,
                note=text,
                capture_id=row.capture_id,
            )
            meeting_id = _uuid(result.get("meeting_id"))
            if meeting_id is not None:
                row.meeting_id = meeting_id
    return voice_handoff_view(db, row)


def cancel_voice_attempt(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    session_id: UUID,
    client: TwilioCallClient | None = None,
) -> dict:
    row = _session(db, tenant_id, session_id)
    if row is None:
        return _denied("The call is not in this workspace.")
    row.operation_token = uuid4().hex
    row.call_authorized = False
    if row.provider_call_id and client is not None:
        status, _payload = client.cancel_call(row.provider_call_id)
        if status in {200, 204}:
            row.status = "cancelled"
            row.outcome = "cancelled"
            row.blocker = "The provider accepted the cancellation."
            return _view_state(row)
        row.status = "cancel_unresolved"
        row.blocker = "The provider did not confirm cancellation. The call was not placed again."
        return _view_state(row)
    row.status = "cancelled"
    if row.provider_call_id:
        row.blocker = "Cancellation was recorded locally. The provider call was not confirmed cancelled."
    else:
        row.blocker = "The call was cancelled before it was placed."
    return _view_state(row)


def voice_for_conversation(db: Session, conversation: Conversation) -> dict | None:
    row = db.scalar(
        select(VoiceSession).where(
            VoiceSession.tenant_id == conversation.tenant_id,
            VoiceSession.conversation_id == conversation.id,
            VoiceSession.deleted_at.is_(None),
        )
    )
    if row is None:
        return None
    return voice_handoff_view(db, row)


def voice_handoff_view(db: Session, row: VoiceSession) -> dict:
    context = _json_dict(row.context_json)
    evidence = _json_dict(row.consent_evidence_json)
    owner = db.get(User, row.owner_id) if row.owner_id is not None else None
    if owner is not None and owner.tenant_id != row.tenant_id:
        owner = None
    events = _events(row)
    last = events[-1] if events else {}
    conversation = db.get(Conversation, row.conversation_id) if row.conversation_id else None
    transcript = ""
    if conversation is not None and conversation.tenant_id == row.tenant_id:
        transcript = (conversation.transcript or "").strip()
    return {
        "session_id": str(row.id),
        "purpose": row.purpose or "",
        "product_name": str(context.get("customer_facing_name") or ""),
        "permission_source": str(evidence.get("source") or ""),
        "permission_channel": str(evidence.get("channel") or ""),
        "permission_scope": str(evidence.get("scope") or ""),
        "permission_at": str(evidence.get("evidenced_at") or ""),
        "execution_authorized": bool(row.call_authorized) and row.status not in {"cancelled", "review"},
        "owner_name": owner.name if owner is not None else "",
        "recipient": row.recipient_e164 or "",
        "caller_identity": row.caller_identity or "",
        "window_start": row.window_start.isoformat() if row.window_start is not None else "",
        "window_end": row.window_end.isoformat() if row.window_end is not None else "",
        "status": row.status or "",
        "attempt_count": int(row.attempt_count or 0),
        "provider_call_id": row.provider_call_id or "",
        "fixture": True,
        "outcome": row.outcome or "",
        "last_event": str(last.get("status") or row.last_event or ""),
        "blocker": row.blocker or "",
        "recording": "Not authorized" if not row.recording_authorized else "Blocked: recording policy is not configured",
        "transcript": "Untrusted transcript stored" if transcript else "No transcript is stored.",
        "handoff_task_id": str(row.handoff_task_id or ""),
        "meeting_id": str(row.meeting_id or ""),
        "transfer": "Not requested" if row.handoff_task_id is None else "Requested. A transfer was not completed.",
        "live_execution_ready": False,
        "next_action": _next_action(row),
    }


def _open_session(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    capture_id: UUID | None,
    purpose: str,
    evidence: dict,
    window_start: datetime | None,
    window_end: datetime | None,
) -> dict:
    if lead.opt_out:
        return _denied("The lead has opted out.")
    contact = _contact(db, tenant_id, lead)
    if contact is None:
        return _denied("No contact is bound to this lead.")
    if contact.opt_out:
        return _denied("The contact has opted out.")
    capture = _bound_capture(db, tenant_id, lead, capture_id)
    if isinstance(capture, str):
        return _denied(capture)
    recipient = _validated_number(contact.phone)
    if not recipient:
        return _denied("The recipient number is missing or not a valid international number.")
    owner = _owner(db, tenant_id, lead)
    context = context_for_lead(db, tenant_id, lead)
    if not context.customer_facing_name:
        return _denied("No frozen product is stored for this lead.")
    existing = _existing(db, tenant_id, lead.id, capture.id if capture is not None else None, purpose)
    if existing is not None:
        return {"status": existing.status, "session_id": str(existing.id), "blocker": existing.blocker}
    conversation = Conversation(
        tenant_id=tenant_id,
        created_by=actor_id,
        channel="voice",
        contact_id=contact.id,
        lead_id=lead.id,
        subject=f"Fixture callback: {context.customer_facing_name}",
        status="open",
        consent=False,
        provider="twilio-fixture",
        is_mock=True,
        transcript="",
        summary="",
    )
    db.add(conversation)
    db.flush()
    row = VoiceSession(
        tenant_id=tenant_id,
        created_by=actor_id,
        conversation_id=conversation.id,
        contact_id=contact.id,
        lead_id=lead.id,
        capture_id=capture.id if capture is not None else None,
        operating_plan_id=lead.operating_plan_id,
        owner_id=owner.id if owner is not None else None,
        carrier="twilio",
        conversation_provider="twilio-fixture",
        destination=recipient,
        recipient_e164=recipient,
        purpose=purpose,
        window_start=window_start,
        window_end=window_end,
        consent_evidence_json=json.dumps(evidence),
        context_json=json.dumps(context.as_dict()),
        status="review",
        fixture=True,
        call_authorized=False,
        recording_authorized=False,
    )
    db.add(row)
    db.flush()
    task = Task(
        tenant_id=tenant_id,
        created_by=actor_id,
        title="Review the requested callback",
        description=f"Purpose: {purpose}\nOwner: {owner.name if owner is not None else 'Unassigned'}\nRecipient: {recipient}",
        status="open",
        priority="medium",
        owner_id=owner.id if owner is not None else None,
        entity_type="lead",
        entity_id=str(lead.id),
        source="human",
    )
    db.add(task)
    db.flush()
    evidence["review_task_id"] = str(task.id)
    row.consent_evidence_json = json.dumps(evidence)
    _link(db, tenant_id, actor_id, lead.id, str(conversation.id))
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="voice.callback_requested",
        title="Callback requested",
        body=purpose,
        actor_type="human",
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="voice.callback_requested",
        entity_type="voice_session",
        entity_id=str(row.id),
        payload={"fixture": True, "purpose": purpose},
    )
    blocker = "" if owner is not None else "Assign an owner before authorizing the call."
    row.blocker = blocker
    return {"status": row.status, "session_id": str(row.id), "blocker": blocker}


def _execution_blocker(db: Session, tenant_id: UUID, actor_id: UUID, row: VoiceSession, now: datetime | None) -> str:
    evidence = _json_dict(row.consent_evidence_json)
    if evidence.get("channel") == "email" or evidence.get("scope") not in _ALLOWED_SCOPE:
        return "Email permission does not authorize a call."
    if not evidence.get("source") or not evidence.get("evidenced_at") or not evidence.get("purpose"):
        return "Call permission is not recorded."
    lead = _lead(db, tenant_id, row.lead_id)
    if lead is None:
        return "The lead is not in this workspace."
    if lead.opt_out:
        return "The lead has opted out."
    contact = _contact(db, tenant_id, lead)
    if contact is None or contact.opt_out:
        return "The contact has opted out."
    recipient = _validated_number(contact.phone)
    if not recipient or recipient != row.recipient_e164:
        return "The recipient number is missing or not a valid international number."
    owner = _owner(db, tenant_id, lead)
    if owner is None or row.owner_id != owner.id:
        return "The assigned owner is not available."
    account = _connection(db, tenant_id, owner.id)
    if account is None:
        return "No authorized voice connection is available for this owner."
    config = _config(account)
    caller = _validated_number(str(config.get("from_number") or ""))
    token = str(config.get("auth_token") or "")
    if not _ACCOUNT_SID.fullmatch(account.provider_account_id or "") or not caller or not token:
        return "The voice connection is missing a caller identity."
    if not _json_dict(row.context_json).get("customer_facing_name"):
        return "No frozen product is stored for this lead."
    moment = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if row.window_start is not None and row.window_end is not None:
        if moment < _aware(row.window_start) or moment >= _aware(row.window_end):
            return "The requested calling window is closed."
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    if in_quiet_hours(settings, moment):
        return "The configured calling window is closed."
    india = _india_block(recipient, contact, moment)
    if india:
        return india
    if not row.provider_call_id and _placed_today(db, tenant_id, row.id, moment) >= int(settings.max_calls_per_day or 0):
        return "The configured call limit is exhausted."
    row.provider_connection_id = account.id
    row.caller_identity = caller
    row.owner_id = owner.id
    return ""


def _apply_create(db: Session, tenant_id: UUID, actor_id: UUID, row: VoiceSession, action, status: int, payload: dict) -> dict:
    sid = str(payload.get("sid") or "").strip()
    if status in {401, 403, 429}:
        action.status = "DEAD_LETTER"
        row.status = "blocked"
        return _stop(row, "The provider refused the call. It was not repeated.")
    if status < 200 or status >= 300 or not sid:
        action.status = "UNRESOLVED"
        row.status = "unresolved"
        return _stop(row, "The call create did not return a call id. It was not repeated.")
    row.provider_call_id = sid
    row.status = _STATUS.get(str(payload.get("status") or "queued").lower(), "queued")
    row.last_event = row.status
    row.outcome = ""
    row.blocker = ""
    db.flush()
    confirm_action(action, provider="twilio", external_id=sid, response_summary="Fixture call created.")
    conversation = db.get(Conversation, row.conversation_id) if row.conversation_id else None
    if conversation is not None:
        conversation.provider_thread_id = sid
        conversation.call_status = row.status
        conversation.is_mock = True
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="voice.call_created",
        entity_type="voice_session",
        entity_id=str(row.id),
        payload={"fixture": True, "provider_call_id": sid},
    )
    return _view_state(row)


def _reconcile_known(db: Session, row: VoiceSession, client: TwilioCallClient | None) -> dict:
    if client is None:
        return _view_state(row)
    status, payload = client.read_call(row.provider_call_id)
    if status == 200 and str(payload.get("sid") or "") == row.provider_call_id:
        mapped = _STATUS.get(str(payload.get("status") or "").lower(), "")
        if mapped:
            row.status = mapped
            row.last_event = mapped
    return _view_state(row)


def _reconcile_unknown(db: Session, row: VoiceSession, client: TwilioCallClient | None, action) -> dict:
    _ = db, client, action
    if row.provider_call_id:
        return _reconcile_known(db, row, client)
    row.status = "unresolved"
    row.blocker = "The previous create is unresolved. Another call was not placed."
    return _view_state(row)


def _handoff(db: Session, tenant_id: UUID, actor_id: UUID, row: VoiceSession) -> None:
    if row.handoff_task_id is not None:
        return
    owner = db.get(User, row.owner_id) if row.owner_id is not None else None
    task = Task(
        tenant_id=tenant_id,
        created_by=actor_id,
        title="Call the person back",
        description=(
            f"Owner: {owner.name if owner is not None else 'Unassigned'}\n"
            "Reason: The person asked for a human.\n"
            "Urgency: normal\n"
            "Next action: The owner returns the call. A transfer was requested and was not completed."
        ),
        status="open",
        priority="high",
        owner_id=row.owner_id,
        entity_type="lead",
        entity_id=str(row.lead_id or ""),
        source="ai",
    )
    db.add(task)
    db.flush()
    row.handoff_task_id = task.id
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(row.lead_id or ""),
        activity_type="voice.handoff_requested",
        title="Human handoff requested",
        body="A transfer was requested and was not completed.",
        actor_type="ai",
    )


def _india_block(phone: str, contact: Contact, moment: datetime) -> str:
    if not phone.startswith("+91"):
        return ""
    ndnc = (contact.ndnc_status or "").strip().upper()
    if ndnc in {"DND", "NDNC", "BLOCKED"}:
        return "Number is on NDNC/DND and cannot be dialed."
    if ndnc != "CLEAR":
        return "NDNC/DND status is unknown. The number stays blocked."
    local = moment.astimezone(ZoneInfo("Asia/Kolkata"))
    if local.weekday() == 6:
        return "The India calling window does not allow Sunday dials."
    minutes = local.hour * 60 + local.minute
    if minutes < 10 * 60 or minutes >= 21 * 60:
        return "The India calling window is 10:00–21:00 IST."
    return ""


def _placed_today(db: Session, tenant_id: UUID, session_id: UUID, moment: datetime) -> int:
    start = moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.scalars(
        select(VoiceSession).where(
            VoiceSession.tenant_id == tenant_id,
            VoiceSession.provider_call_id != "",
            VoiceSession.deleted_at.is_(None),
        )
    ).all()
    return sum(1 for item in rows if item.id != session_id and _aware(item.created_at) >= start)


def _connection(db: Session, tenant_id: UUID, owner_id: UUID) -> ProviderAccount | None:
    rows = db.scalars(
        select(ProviderAccount).where(
            ProviderAccount.tenant_id == tenant_id,
            ProviderAccount.provider == "twilio",
            ProviderAccount.status == "connected",
            ProviderAccount.connected_user_id == owner_id,
            ProviderAccount.deleted_at.is_(None),
        )
    ).all()
    if len(rows) != 1:
        return None
    return rows[0]


def _existing(db: Session, tenant_id: UUID, lead_id: UUID, capture_id: UUID | None, purpose: str) -> VoiceSession | None:
    stmt = select(VoiceSession).where(
        VoiceSession.tenant_id == tenant_id,
        VoiceSession.lead_id == lead_id,
        VoiceSession.purpose == purpose,
        VoiceSession.deleted_at.is_(None),
        VoiceSession.status != "cancelled",
    )
    if capture_id is not None:
        stmt = stmt.where(VoiceSession.capture_id == capture_id)
    return db.scalar(stmt.order_by(VoiceSession.created_at.desc()))


def _bound_capture(db: Session, tenant_id: UUID, lead: Lead, capture_id: UUID | None) -> InboundCapture | str | None:
    if capture_id is None:
        return db.scalar(
            select(InboundCapture)
            .where(
                InboundCapture.tenant_id == tenant_id,
                InboundCapture.lead_id == lead.id,
                InboundCapture.deleted_at.is_(None),
            )
            .order_by(InboundCapture.created_at.desc())
        )
    row = db.get(InboundCapture, capture_id)
    if row is None or row.tenant_id != tenant_id or row.deleted_at is not None or row.lead_id != lead.id:
        return "The enquiry is not attached to this lead."
    return row


def _lead(db: Session, tenant_id: UUID, lead_id: UUID | None) -> Lead | None:
    if lead_id is None:
        return None
    row = db.get(Lead, lead_id)
    if row is None or row.tenant_id != tenant_id or row.deleted_at is not None:
        return None
    return row


def _contact(db: Session, tenant_id: UUID, lead: Lead) -> Contact | None:
    if lead.contact_id is None:
        return None
    row = db.get(Contact, lead.contact_id)
    if row is None or row.tenant_id != tenant_id or row.deleted_at is not None:
        return None
    return row


def _owner(db: Session, tenant_id: UUID, lead: Lead) -> User | None:
    if lead.owner_id is None:
        return None
    row = db.get(User, lead.owner_id)
    if row is None or row.tenant_id != tenant_id or not row.is_active:
        return None
    return row


def _session(db: Session, tenant_id: UUID, session_id: UUID | None) -> VoiceSession | None:
    if session_id is None:
        return None
    row = db.get(VoiceSession, session_id)
    if row is None or row.tenant_id != tenant_id or row.deleted_at is not None:
        return None
    return row


def _config(account: ProviderAccount | None) -> dict:
    if account is None:
        return {}
    try:
        loaded = json.loads(account.config_encrypted or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _validated_number(raw: str) -> str:
    text = (raw or "").strip()
    if _E164.fullmatch(text):
        return text
    return ""


def _parse_window(start: str, end: str) -> tuple[datetime | None, datetime | None, str]:
    if not (start or "").strip() and not (end or "").strip():
        return None, None, ""
    if not (start or "").strip() or not (end or "").strip():
        return None, None, "The requested calling window is incomplete."
    try:
        left = datetime.fromisoformat(start)
        right = datetime.fromisoformat(end)
    except ValueError:
        return None, None, "The requested calling window is not a valid time."
    if left.tzinfo is None or right.tzinfo is None:
        return None, None, "The requested calling window has no time zone."
    if right <= left:
        return None, None, "The requested calling window is empty."
    return left.astimezone(UTC), right.astimezone(UTC), ""


def _twilio_signature(url: str, params: dict[str, str], token: str) -> str:
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _sequence(raw: str | None) -> int | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _events(row: VoiceSession) -> list[dict]:
    try:
        loaded = json.loads(row.events_json or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in loaded if isinstance(item, dict)] if isinstance(loaded, list) else []


def _link(db: Session, tenant_id: UUID, actor_id: UUID, lead_id: UUID, conversation_id: str) -> None:
    key = f"lead:{lead_id}"
    existing = db.scalar(
        select(JourneyLink.id).where(
            JourneyLink.tenant_id == tenant_id,
            JourneyLink.journey_key == key,
            JourneyLink.entity_type == "conversation",
            JourneyLink.entity_id == conversation_id,
            JourneyLink.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return
    db.add(
        JourneyLink(
            tenant_id=tenant_id,
            created_by=actor_id,
            journey_key=key,
            entity_type="conversation",
            entity_id=conversation_id,
            role="callback",
        )
    )


def _next_action(row: VoiceSession) -> str:
    if row.blocker:
        return row.blocker
    if row.handoff_task_id is not None:
        return "The owner returns the call. A transfer was not completed."
    if row.meeting_id is not None:
        return "Select a slot and authorize booking. The call did not book a meeting."
    if row.status == "completed":
        return "The call completed. A useful conversation is not recorded."
    if row.provider_call_id:
        return "Wait for a verified provider status."
    if row.call_authorized:
        return "The attempt is authorized and has not been placed."
    return "Review the callback. It is not authorized to dial."


def _view_state(row: VoiceSession) -> dict:
    return {
        "status": row.status,
        "session_id": str(row.id),
        "provider_call_id": row.provider_call_id,
        "blocker": row.blocker,
        "meeting_id": str(row.meeting_id or ""),
        "handoff_task_id": str(row.handoff_task_id or ""),
        "outcome": row.outcome,
    }


def _stop(row: VoiceSession, blocker: str) -> dict:
    row.blocker = blocker
    if row.status not in _TERMINAL | {"unresolved", "cancelled", "cancel_unresolved"}:
        row.status = "blocked" if row.provider_call_id == "" else row.status
    return _view_state(row)


def _denied(blocker: str) -> dict:
    return {"status": "blocked", "session_id": "", "blocker": blocker}


def _json_dict(raw: str) -> dict:
    try:
        loaded = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
