import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.models.ai import AIApproval
from app.models.crm import Contact, Lead
from app.models.funnel import VoiceSession
from app.models.lifecycle import Conversation, MeetingRecord
from app.providers.voice import normalize_call_status
from app.services.audit import emit_event, write_audit
from app.services.autopilot_settings import get_or_create_settings
from app.services.consent import assert_can_dial, assert_can_dial_india
from app.services.crm import add_activity
from app.services.idempotency import claim_daily_slot, claim_key
from app.services.meeting_intelligence import apply_meeting_insights, extract_insights
from app.services.provider_metrics import VOICE_CALLS, VOICE_COMPLETED, VOICE_FAILED
from app.services.provider_ops import (
    begin_action,
    block_action,
    confirm_action,
    fail_action,
    is_circuit_open,
    record_provider_result,
)
from app.services.query import get_owned
from app.services.voice_router import destination_region, get_voice_provider


def queue_voice_dial(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    contact_id: UUID,
    consent: bool,
    correlation_id: str = "",
    run_id: UUID | None = None,
) -> AIApproval:
    contact = get_owned(db, Contact, tenant_id, contact_id)
    assert_can_dial(contact, consent=consent)
    assert_can_dial_india(contact)
    key = f"voice.dial.queue:{contact.id}"
    fresh, existing = claim_key(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        key=key,
        workflow="voice",
        entity_id=str(contact.id),
        action_type="voice.dial",
    )
    if not fresh:
        prior = db.scalar(
            select(AIApproval).where(
                AIApproval.tenant_id == tenant_id,
                AIApproval.idempotency_key == key,
                AIApproval.deleted_at.is_(None),
            )
        )
        if prior is not None:
            return prior
        _ = existing
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="voice.dial",
        title=f"Dial {contact.first_name} {contact.last_name}",
        payload_json=json.dumps({"contact_id": str(contact.id), "phone": contact.phone}),
        status="pending",
        entity_type="contact",
        entity_id=str(contact.id),
        run_id=run_id,
        idempotency_key=key,
    )
    db.add(approval)
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="voice.dial_requested",
        entity_type="contact",
        entity_id=str(contact.id),
        correlation_id=correlation_id,
    )
    db.flush()
    return approval


def execute_voice_dial(db: Session, *, tenant_id: UUID, actor_id: UUID, approval: AIApproval) -> str:
    payload = json.loads(approval.payload_json or "{}")
    contact_id = payload.get("contact_id")
    if not contact_id:
        return "No contact on this approval. No dial was placed."
    contact = get_owned(db, Contact, tenant_id, UUID(contact_id))
    try:
        assert_can_dial(contact, consent=True)
        assert_can_dial_india(contact)
    except HTTPException as exc:
        return str(exc.detail)
    key = f"voice.dial:{tenant_id}:{approval.id}"
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="voice.dial",
        idempotency_key=key,
        provider="voice",
        approval_id=approval.id,
        entity_type="contact",
        entity_id=str(contact.id),
        request_summary="dial",
    )
    if action.status == "CONFIRMED" and action.external_id:
        return f"Dial already confirmed as {action.external_id}."
    if action.status == "BLOCKED":
        return action.last_error or "Dial was not placed."
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    if not claim_daily_slot(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        kind="voice",
        limit=settings.max_calls_per_day,
    ):
        return "Daily voice cap reached. No dial was placed."
    if is_circuit_open(db, tenant_id=tenant_id, provider="voice"):
        block_action(action, reason="Provider circuit is open", failure_class="TRANSIENT")
        return "Blocked by provider. No dial was placed."
    provider = get_voice_provider(db, tenant_id, contact.phone)
    health = provider.health()
    if health.is_mock or not health.connected:
        block_action(action, reason=health.reason, failure_class="CONFIGURATION")
        record_provider_result(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            provider=health.provider,
            action="voice.dial",
            ok=False,
            failure_class="CONFIGURATION",
            error=health.reason,
        )
        row = Conversation(
            tenant_id=tenant_id,
            created_by=actor_id,
            channel="voice",
            account_id=contact.account_id,
            contact_id=contact.id,
            subject=f"Gated dial to {contact.first_name} {contact.last_name}",
            status="refused",
            consent=True,
            provider=health.provider,
            is_mock=health.is_mock,
            transcript="",
            summary=health.reason,
            call_status="FAILED",
        )
        db.add(row)
        return health.reason or "Dial was not placed."
    session = provider.start_session(to_number=contact.phone, from_label="AGRAYIAN")
    record_provider_result(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        provider=session.provider,
        action="voice.dial",
        ok=session.ok,
        failure_class=session.failure_class,
        error=session.reason,
    )
    row = Conversation(
        tenant_id=tenant_id,
        created_by=actor_id,
        channel="voice",
        account_id=contact.account_id,
        contact_id=contact.id,
        subject=f"Gated dial to {contact.first_name} {contact.last_name}",
        status="open" if session.ok else "refused",
        consent=True,
        provider=session.provider,
        is_mock=session.is_mock,
        transcript="",
        summary=session.reason or session.session_id,
        provider_thread_id=session.session_id,
        call_status=session.call_status or ("QUEUED" if session.ok else "FAILED"),
    )
    db.add(row)
    db.flush()
    evidence = {
        "consent_voice": True,
        "consent_recording": bool(getattr(contact, "consent_recording", False)),
        "ndnc_status": getattr(contact, "ndnc_status", "") or "",
        "announcement": "This call may be recorded.",
    }
    db.add(
        VoiceSession(
            tenant_id=tenant_id,
            created_by=actor_id,
            conversation_id=row.id,
            contact_id=contact.id,
            approval_id=approval.id,
            carrier=session.provider,
            conversation_provider=getattr(provider, "conversation_name", ""),
            region=destination_region(contact.phone),
            destination=contact.phone,
            provider_call_id=session.session_id,
            consent_evidence_json=json.dumps(evidence),
            ndnc_status=getattr(contact, "ndnc_status", "") or "",
            status=session.call_status or ("QUEUED" if session.ok else "FAILED"),
            announcement_played=destination_region(contact.phone) == "IN",
        )
    )
    VOICE_CALLS.labels(provider=session.provider[:40]).inc()
    if not session.ok:
        fail_action(action, failure_class=session.failure_class or "TRANSIENT", error=session.reason, retryable=session.failure_class == "TRANSIENT")
        VOICE_FAILED.labels(provider=session.provider[:40]).inc()
        return session.reason or "Dial was not placed."
    confirm_action(action, provider=session.provider, external_id=session.session_id, response_summary=f"conversation={row.id}")
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="voice.dialed",
        entity_type="contact",
        entity_id=str(contact.id),
        payload={"conversation_id": str(row.id), "provider_call_id": session.session_id},
    )
    return f"Session {session.session_id} started on {session.provider}."


def _lead_for_contact(db: Session, tenant_id: UUID, contact: Contact) -> Lead | None:
    return db.scalar(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.contact_id == contact.id, Lead.deleted_at.is_(None))
    )


def apply_call_outcome(db: Session, *, tenant_id: UUID, actor_id: UUID, conversation: Conversation, transcript: str = "") -> str:
    text = (transcript or conversation.transcript or "").lower()
    contact = None
    if conversation.contact_id:
        contact = db.scalar(
            select(Contact).where(Contact.id == conversation.contact_id, Contact.tenant_id == tenant_id, Contact.deleted_at.is_(None))
        )
    lead = _lead_for_contact(db, tenant_id, contact) if contact else None
    if any(token in text for token in ("do not call", "unsubscribe", "remove me", "stop calling")):
        conversation.outcome = "do_not_call"
        if contact:
            contact.opt_out = True
            contact.preferred_channel = "NONE"
        if lead:
            lead.opt_out = True
            lead.status = "unqualified"
        emit_event(db, tenant_id=tenant_id, event_type="voice.suppressed", entity_type="contact", entity_id=str(conversation.contact_id or ""))
        return "suppressed"
    if conversation.call_status in {"NO_ANSWER", "BUSY"}:
        conversation.outcome = conversation.call_status.lower()
        if lead:
            emit_event(db, tenant_id=tenant_id, event_type="sequence.followup", entity_type="lead", entity_id=str(lead.id))
        return "followup"
    if any(token in text for token in ("not interested", "no thanks", "don't call")):
        conversation.outcome = "not_interested"
        if lead:
            lead.status = "nurture"
        return "nurture"
    if any(token in text for token in ("meeting", "calendar", "schedule", "book a")):
        conversation.outcome = "meeting_request"
        if lead:
            emit_event(db, tenant_id=tenant_id, event_type="meeting.requested", entity_type="lead", entity_id=str(lead.id))
        return "meeting"
    if any(token in text for token in ("interested", "send a proposal", "next step", "sounds good")):
        conversation.outcome = "positive"
        if lead and lead.status in {"new", "working", "nurture"}:
            lead.status = "qualified"
            emit_event(db, tenant_id=tenant_id, event_type="lead.qualified", entity_type="lead", entity_id=str(lead.id))
        return "qualified"
    return conversation.outcome or ""


def apply_call_event(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    provider: str,
    payload: dict,
) -> str:
    external_id = str(
        payload.get("CallSid")
        or payload.get("Sid")
        or payload.get("call_id")
        or payload.get("id")
        or payload.get("external_id")
        or payload.get("provider_call_id")
        or ""
    )
    if not external_id:
        return "missing_call_id"
    conversation = db.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.provider_thread_id == external_id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(Conversation.created_at.desc())
    )
    if conversation is None:
        return "unknown_call"
    raw_status = str(payload.get("CallStatus") or payload.get("status") or payload.get("endedReason") or "")
    normalized = normalize_call_status(raw_status)
    if normalized:
        conversation.call_status = normalized
    transcript = str(payload.get("transcript") or payload.get("TranscriptionText") or payload.get("artifact.transcript") or "")
    if not transcript and isinstance(payload.get("artifact"), dict):
        transcript = str(payload["artifact"].get("transcript") or "")
    if not transcript and isinstance(payload.get("message"), dict):
        transcript = str(payload["message"].get("transcript") or "")
    if transcript.strip():
        ingested = get_voice_provider(db, tenant_id).ingest_transcript(session_id=external_id, transcript=transcript)
        if ingested.ok:
            conversation.transcript = ingested.transcript
    if conversation.call_status == "COMPLETED":
        conversation.status = "closed"
        VOICE_COMPLETED.labels(provider=provider[:40]).inc()
    if conversation.call_status in {"FAILED", "CANCELLED", "NO_ANSWER", "BUSY"}:
        if conversation.call_status == "FAILED":
            VOICE_FAILED.labels(provider=provider[:40]).inc()
    apply_call_outcome(db, tenant_id=tenant_id, actor_id=actor_id, conversation=conversation, transcript=conversation.transcript)
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="contact",
        entity_id=str(conversation.contact_id or ""),
        activity_type="voice",
        title=f"Call {conversation.call_status or 'updated'}",
        body=conversation.outcome,
        actor_type="ai",
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="voice.status",
        entity_type="conversation",
        entity_id=str(conversation.id),
        payload={"call_status": conversation.call_status, "outcome": conversation.outcome},
    )
    record_provider_result(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        provider=provider,
        action="voice.callback",
        ok=True,
    )
    return "processed"


def extract_meeting_notes(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    transcript: str,
    title: str,
    account_id: UUID | None,
    opportunity_id: UUID | None,
    correlation_id: str = "",
) -> MeetingRecord:
    ingested = get_voice_provider(db, tenant_id).ingest_transcript(session_id="", transcript=transcript)
    if not ingested.ok:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Transcript is required.")
    llm = get_llm_provider(db, tenant_id)
    completion = llm.complete(
        f"Untrusted transcript:\n{ingested.transcript}\n\nExtract key points and one next step using only statements present above. Cite the transcript or abstain. Do not invent attendees, quotes, or numbers.",
        system="You extract meeting notes. If the transcript is insufficient, say you cannot extract a next step. Never invent quotes.",
    )
    text = completion.text.strip()
    next_steps = ""
    summary = text
    if "next step" in text.lower():
        parts = text.split("\n")
        for line in parts:
            if "next step" in line.lower():
                next_steps = line.strip()
                break
    row = MeetingRecord(
        tenant_id=tenant_id,
        created_by=actor_id,
        account_id=account_id,
        opportunity_id=opportunity_id,
        title=title or "Extracted meeting notes",
        occurred_at=datetime.now(UTC),
        summary=summary[:4000],
        next_steps=next_steps[:500],
        provider=ingested.provider,
        is_mock=ingested.is_mock or completion.is_mock,
    )
    db.add(row)
    db.flush()
    insights = extract_insights(transcript=ingested.transcript, db=db, tenant_id=tenant_id)
    apply_meeting_insights(db, tenant_id=tenant_id, actor_id=actor_id, meeting=row, insights=insights)
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="meeting.extract",
        entity_type="meeting",
        after={"provider": ingested.provider, "is_mock": row.is_mock},
        correlation_id=correlation_id,
        actor_type="ai",
    )
    db.flush()
    return row
