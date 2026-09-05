import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.models.ai import AIApproval
from app.models.crm import Contact
from app.models.lifecycle import Conversation, MeetingRecord
from app.providers.voice import get_voice_provider
from app.services.audit import write_audit
from app.services.consent import assert_can_dial
from app.services.query import get_owned


def queue_voice_dial(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    contact_id: UUID,
    consent: bool,
    correlation_id: str = "",
) -> AIApproval:
    contact = get_owned(db, Contact, tenant_id, contact_id)
    assert_can_dial(contact, consent=consent)
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="voice.dial",
        title=f"Dial {contact.first_name} {contact.last_name}",
        payload_json=json.dumps({"contact_id": str(contact.id), "phone": contact.phone}),
        status="pending",
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
    if contact.opt_out:
        return "Contact opted out. Dial refused."
    provider = get_voice_provider()
    session = provider.start_session(to_number=contact.phone, from_label="AGRAYIAN")
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
    )
    db.add(row)
    if not session.ok:
        return session.reason or "Dial was not placed."
    return f"Session {session.session_id} started on {session.provider}."


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
    ingested = get_voice_provider().ingest_transcript(session_id="", transcript=transcript)
    if not ingested.ok:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Transcript is required.")
    llm = get_llm_provider()
    completion = llm.complete(
        f"Transcript:\n{ingested.transcript}\n\nExtract key points and one next step. Cite the transcript or abstain. Do not invent attendees or numbers.",
        system="You extract meeting notes. If the transcript is insufficient, say you cannot extract a next step.",
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
