import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import assert_never
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval, AIRecommendation
from app.models.assessment import AssessmentEvidence
from app.models.crm import Contact, Lead, Task
from app.models.execution import ActionRequest
from app.models.integrations import EmailMessage
from app.models.lifecycle import Conversation, SequenceEnrollment
from app.services.automation_state import upsert_state
from app.services.autopilot_settings import get_or_create_settings
from app.services.calendar_booking import queue_meeting_proposal
from app.services.crm import add_activity
from app.services.mail_origin import LOOP_LIMIT, automated_inbound_count, headers_of, message_origin
from app.services.operations import connected_mailbox_address
from app.services.qualification import qualify_lead
from app.services.reply_intelligence import ReplyCategory, _normalize_category


def _cancel_pending_sends(db: Session, *, tenant_id: UUID, lead_id: UUID, action_types: set[str] | None = None) -> None:
    requests = db.scalars(
        select(ActionRequest).where(
            ActionRequest.tenant_id == tenant_id,
            ActionRequest.entity_id == str(lead_id),
            ActionRequest.status.in_(["pending", "approved", "deferred", "queued"]),
            ActionRequest.deleted_at.is_(None),
        )
    ).all()
    for request in requests:
        if _matches_followup(request.action_type, action_types) or (action_types is None and request.channel == "email"):
            request.status = "cancelled"
            request.result = "Cancelled after an inbound reply."
    rows = db.scalars(
        select(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.entity_id == str(lead_id),
            AIApproval.status == "pending",
            AIApproval.deleted_at.is_(None),
        )
    ).all()
    for row in rows:
        if _matches_followup(row.action_type, action_types):
            row.status = "cancelled"
            row.decision_note = "Cancelled after inbound reply policy."


def _matches_followup(action_type: str, action_types: set[str] | None) -> bool:
    if action_types is None:
        return action_type.endswith(".send") or action_type == "email.acknowledge"
    return action_type in action_types


def _record_reply_evidence(db: Session, *, tenant_id: UUID, actor_id: UUID, lead: Lead, message: EmailMessage) -> None:
    excerpt = (message.body_text or "")[:1000]
    digest = hashlib.sha256(f"{message.id}|{excerpt}".encode()).hexdigest()
    person_id = str(lead.contact_id or lead.id)
    existing = db.scalar(
        select(AssessmentEvidence.id).where(
            AssessmentEvidence.tenant_id == tenant_id,
            AssessmentEvidence.person_id == person_id,
            AssessmentEvidence.kind == "reply",
            AssessmentEvidence.source == "email",
            AssessmentEvidence.content_hash == digest,
            AssessmentEvidence.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return
    db.add(
        AssessmentEvidence(
            tenant_id=tenant_id,
            created_by=actor_id,
            person_id=person_id,
            kind="reply",
            source="email",
            content_hash=digest,
            polarity="neutral",
            observed_at=message.received_at or datetime.now(UTC),
            excerpt=excerpt,
        )
    )
    db.flush()


def _review_task(db: Session, *, tenant_id: UUID, actor_id: UUID, lead: Lead, message: EmailMessage) -> None:
    description = f"message:{message.id}"
    existing = db.scalar(
        select(Task.id).where(
            Task.tenant_id == tenant_id,
            Task.entity_type == "lead",
            Task.entity_id == str(lead.id),
            Task.description == description,
            Task.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return
    db.add(
        Task(
            tenant_id=tenant_id,
            created_by=actor_id,
            title="Review an uncertain reply",
            description=description,
            status="open",
            priority="high",
            owner_id=lead.owner_id or actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            source="review",
        )
    )


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


def _defer_out_of_office(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    until: object,
    run_id: UUID | None,
) -> str:
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
    shown = until or pause_until.date().isoformat()
    upsert_state(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        state="PAUSED",
        last_action="out_of_office",
        next_action="resume_after_ooo",
        blocked_reason=f"Out of office until {shown}",
        run_id=run_id,
    )
    return "paused_ooo"


def _stop_automated(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    message: EmailMessage,
    origin: str,
    run_id: UUID | None,
) -> str:
    message.classification = "BOUNCE" if origin == "bounce" else "AUTOMATED"
    _cancel_pending_sends(db, tenant_id=tenant_id, lead_id=lead.id)
    if origin == "bounce":
        _stop_enrollments(db, tenant_id=tenant_id, lead_id=lead.id)
    count = automated_inbound_count(db, tenant_id=tenant_id, conversation_id=message.conversation_id)
    if count >= LOOP_LIMIT:
        conversation = db.get(Conversation, message.conversation_id)
        if conversation is not None and conversation.tenant_id == tenant_id:
            conversation.status = "loop_stopped"
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="PAUSED",
            last_action="automated_loop_stopped",
            next_action="review_automated_mail",
            blocked_reason="Automated exchange stopped. The thread reached the response limit for this hour.",
            run_id=run_id,
        )
        return "loop_stopped"
    reason = "Delivery failed. No sales response was sent." if origin == "bounce" else "Automated message. No sales response was sent."
    upsert_state(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        state="PAUSED",
        last_action="bounce" if origin == "bounce" else "automated_message",
        next_action="review_automated_mail",
        blocked_reason=reason,
        run_id=run_id,
    )
    return "bounce" if origin == "bounce" else "automated_ignored"


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
    mailbox = connected_mailbox_address(db, tenant_id)
    origin = message_origin(
        from_addr=message.from_addr,
        subject=message.subject,
        body=message.body_text,
        mailbox=mailbox,
        headers=headers_of(message),
    )
    _record_reply_evidence(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, message=message)
    if origin == "self":
        message.classification = "SELF"
        return "self_reply"
    if origin in {"automated", "bounce"}:
        return _stop_automated(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, message=message, origin=origin, run_id=run_id)
    if origin == "out_of_office":
        message.classification = "OUT_OF_OFFICE"
        return _defer_out_of_office(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            until=classification.get("out_of_office_until"),
            run_id=run_id,
        )
    if category == "UNSUBSCRIBE":
        lead.opt_out = True
        lead.consent_email = False
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    qualification = qualify_lead(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        lead=lead,
        settings=settings,
        meeting_requested=category == "MEETING_REQUEST" or "meet" in (message.body_text or "").casefold(),
    )
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
        _cancel_pending_sends(db, tenant_id=tenant_id, lead_id=lead.id, action_types={"sequence.email.send"})
        _stop_enrollments(db, tenant_id=tenant_id, lead_id=lead.id)
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
    if category == "MEETING_REQUEST":
        _cancel_pending_sends(db, tenant_id=tenant_id, lead_id=lead.id, action_types={"sequence.email.send"})
        _stop_enrollments(db, tenant_id=tenant_id, lead_id=lead.id)
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
    if category == "POSITIVE_INTEREST":
        if qualification.get("response_eligible"):
            upsert_state(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entity_type="lead",
                entity_id=str(lead.id),
                state="WAITING_FOR_CUSTOMER",
                last_action="response_eligible",
                next_action="acknowledge",
                blocked_reason="",
                run_id=run_id,
            )
            return "response_eligible"
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="qualification_incomplete",
            next_action="complete_qualification",
            blocked_reason="A positive reply is not a sales-qualified meeting until qualification passes",
            run_id=run_id,
        )
        return "qualification_required"
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
        _review_task(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, message=message)
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="WAITING_FOR_REVIEW",
            last_action="uncertain_reply",
            next_action="review_reply",
            blocked_reason="The reply classification is uncertain.",
            run_id=run_id,
        )
        return "uncertain"
    assert_never(category)
