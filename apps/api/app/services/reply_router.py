import json
from datetime import UTC, datetime, timedelta
from typing import assert_never
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval, AIRecommendation
from app.models.crm import Contact, Lead
from app.models.integrations import EmailMessage
from app.models.lifecycle import SequenceEnrollment
from app.services.automation_state import upsert_state
from app.services.autopilot_settings import get_or_create_settings
from app.services.calendar_booking import queue_meeting_proposal
from app.services.crm import add_activity
from app.services.qualification import qualify_lead
from app.services.reply_intelligence import ReplyCategory, _normalize_category


def _cancel_pending_sends(db: Session, *, tenant_id: UUID, lead_id: UUID) -> None:
    rows = db.scalars(
        select(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.entity_id == str(lead_id),
            AIApproval.status == "pending",
            AIApproval.deleted_at.is_(None),
        )
    ).all()
    for row in rows:
        if row.action_type.endswith(".send"):
            row.status = "cancelled"
            row.decision_note = "Cancelled after inbound reply policy."


def _stop_enrollments(db: Session, *, tenant_id: UUID, lead_id: UUID) -> None:
    rows = db.scalars(
        select(SequenceEnrollment).where(
            SequenceEnrollment.tenant_id == tenant_id,
            SequenceEnrollment.lead_id == lead_id,
            SequenceEnrollment.status == "active",
            SequenceEnrollment.deleted_at.is_(None),
        )
    ).all()
    for row in rows:
        row.status = "stopped"
        row.next_run_at = None


def route_reply(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    message: EmailMessage,
    classification: dict,
    run_id: UUID | None = None,
) -> str:
    category: ReplyCategory = _normalize_category(str(classification.get("category") or "UNCERTAIN"))
    title = f"Reply classified as {category.replace('_', ' ').title()}"
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="email",
        title=title,
        body=str(classification.get("summary") or ""),
        actor_type="ai",
    )
    if category == "UNSUBSCRIBE":
        lead.opt_out = True
        lead.consent_email = False
        if lead.contact_id:
            contact = db.scalar(select(Contact).where(Contact.tenant_id == tenant_id, Contact.id == lead.contact_id))
            if contact is not None:
                contact.opt_out = True
                contact.consent_email = False
        _stop_enrollments(db, tenant_id=tenant_id, lead_id=lead.id)
        _cancel_pending_sends(db, tenant_id=tenant_id, lead_id=lead.id)
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="unsubscribed",
            blocked_reason="Lead unsubscribed",
            run_id=run_id,
        )
        return "unsubscribed"
    if category == "OUT_OF_OFFICE":
        until = classification.get("out_of_office_until")
        pause_until = datetime.now(UTC) + timedelta(days=5)
        enrollments = db.scalars(
            select(SequenceEnrollment).where(
                SequenceEnrollment.tenant_id == tenant_id,
                SequenceEnrollment.lead_id == lead.id,
                SequenceEnrollment.status == "active",
            )
        ).all()
        for enrollment in enrollments:
            enrollment.next_run_at = pause_until
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="PAUSED",
            last_action="out_of_office",
            next_action="resume_after_ooo",
            blocked_reason=f"Out of office until {until or pause_until.date().isoformat()}",
            run_id=run_id,
        )
        return "paused_ooo"
    if category == "WRONG_PERSON":
        _stop_enrollments(db, tenant_id=tenant_id, lead_id=lead.id)
        _cancel_pending_sends(db, tenant_id=tenant_id, lead_id=lead.id)
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="wrong_person",
            next_action="research_alternate_contact",
            blocked_reason="Wrong person replied",
            run_id=run_id,
        )
        return "wrong_person"
    if category == "NOT_NOW":
        later = datetime.now(UTC) + timedelta(days=21)
        enrollments = db.scalars(
            select(SequenceEnrollment).where(
                SequenceEnrollment.tenant_id == tenant_id,
                SequenceEnrollment.lead_id == lead.id,
                SequenceEnrollment.status == "active",
            )
        ).all()
        for enrollment in enrollments:
            enrollment.next_run_at = later
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="PAUSED",
            last_action="nurture",
            next_action="resume_nurture",
            blocked_reason="Prospect asked to wait",
            run_id=run_id,
        )
        return "nurture"
    if category in {"QUESTION", "OBJECTION"}:
        key = f"email.reply:{lead.id}:{message.id}"
        exists = db.scalar(
            select(AIApproval).where(
                AIApproval.tenant_id == tenant_id,
                AIApproval.idempotency_key == key,
                AIApproval.deleted_at.is_(None),
            )
        )
        if exists is None:
            db.add(
                AIApproval(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    action_level=2,
                    action_type="email.send",
                    title=f"Reply to {lead.email}",
                    payload_json=json.dumps(
                        {
                            "lead_id": str(lead.id),
                            "thread_id": message.provider_thread_id,
                            "subject": f"Re: {message.subject}",
                            "body": classification.get("suggested_reply") or "Thanks for the note — I'll follow up with a precise answer.",
                            "why": f"Inbound classified as {category}.",
                            "evidence": classification.get("summary"),
                            "risk": "External reply.",
                            "expected_outcome": "Human-approved reply stays on the same thread.",
                        }
                    ),
                    status="pending",
                    run_id=run_id,
                    entity_type="lead",
                    entity_id=str(lead.id),
                    idempotency_key=key,
                )
            )
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="OUTREACH_APPROVAL_PENDING",
            last_action="reply_drafted",
            next_action="approve_reply",
            blocked_reason="",
            run_id=run_id,
        )
        return "reply_queued"
    if category in {"POSITIVE_INTEREST", "MEETING_REQUEST"}:
        settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
        qualify_lead(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, settings=settings)
        queue_meeting_proposal(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, run_id=run_id)
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="OUTREACH_APPROVAL_PENDING",
            last_action="meeting_proposed",
            next_action="approve_meeting_proposal",
            blocked_reason="",
            run_id=run_id,
        )
        return "meeting_proposed"
    if category == "UNCERTAIN":
        updates = classification.get("field_updates") or {}
        if updates:
            db.add(
                AIRecommendation(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    entity_type="lead",
                    entity_id=str(lead.id),
                    kind="reply",
                    title="Uncertain field updates from inbound email",
                    body=json.dumps(updates, default=str),
                    status="draft",
                )
            )
        return "uncertain"
    assert_never(category)
