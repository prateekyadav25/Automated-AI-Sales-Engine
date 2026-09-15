import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.autonomy import AutonomousRun
from app.models.crm import Lead
from app.models.integrations import EmailMessage
from app.models.lifecycle import Conversation, Sequence, SequenceEnrollment, SequenceStep
from app.providers.email import get_email_provider
from app.services.audit import emit_event
from app.services.automation_state import is_entity_paused, upsert_state
from app.services.autopilot_settings import get_or_create_settings, in_quiet_hours
from app.services.consent import assert_can_email, email_block_reason
from app.services.crm import add_activity
from app.services.idempotency import claim_daily_slot, claim_key, remember_result
from app.services.lifecycle import enroll_sequence
from app.services.outreach_limits import outreach_limit_reason
from app.services.policy_versions import current_policy_version
from app.services.provider_ops import begin_action, confirm_action, fail_action


def _payload(row: AIApproval) -> dict:
    try:
        data = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def advance_enrollment(db: Session, enrollment: SequenceEnrollment) -> None:
    nxt = db.scalar(
        select(SequenceStep)
        .where(
            SequenceStep.sequence_id == enrollment.sequence_id,
            SequenceStep.deleted_at.is_(None),
            SequenceStep.position > enrollment.current_step,
        )
        .order_by(SequenceStep.position.asc())
    )
    if nxt is None:
        enrollment.status = "completed"
        enrollment.next_run_at = None
        return
    enrollment.current_step = nxt.position
    enrollment.next_run_at = datetime.now(UTC) + timedelta(days=max(nxt.delay_days, 0))


def find_or_create_thread(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    subject: str,
    provider: str,
    is_mock: bool,
    thread_id: str,
) -> Conversation:
    conversation = None
    if thread_id:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.provider_thread_id == thread_id,
                Conversation.deleted_at.is_(None),
            )
        )
    if conversation is None:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.lead_id == lead.id,
                Conversation.channel == "email",
                Conversation.deleted_at.is_(None),
            )
        )
    if conversation is None:
        conversation = Conversation(
            tenant_id=tenant_id,
            created_by=actor_id,
            channel="email",
            account_id=lead.account_id,
            contact_id=lead.contact_id,
            lead_id=lead.id,
            subject=subject,
            status="open",
            outcome="",
            consent=True,
            provider=provider,
            is_mock=is_mock,
            transcript="",
            summary="",
            provider_thread_id=thread_id,
        )
        db.add(conversation)
        db.flush()
        return conversation
    if thread_id and not conversation.provider_thread_id:
        conversation.provider_thread_id = thread_id
    conversation.lead_id = conversation.lead_id or lead.id
    return conversation


def persisted_send_for_approval(db: Session, tenant_id: UUID, approval_id: UUID) -> EmailMessage | None:
    return db.scalar(
        select(EmailMessage).where(
            EmailMessage.tenant_id == tenant_id,
            EmailMessage.approval_id == approval_id,
            EmailMessage.deleted_at.is_(None),
        )
    )


def execute_email_send(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    approval: AIApproval,
    payload_patch: dict | None = None,
) -> str:
    payload = _payload(approval)
    if payload_patch:
        if payload_patch.get("subject"):
            payload["subject"] = payload_patch["subject"]
        if payload_patch.get("body"):
            payload["body"] = payload_patch["body"]
        approval.payload_json = json.dumps(payload, default=str)
    existing = persisted_send_for_approval(db, tenant_id, approval.id)
    if existing is not None and existing.status == "SENT":
        return f"Provider {existing.provider} recorded send {existing.provider_message_id}."
    lead_id = payload.get("lead_id") or approval.entity_id
    if not lead_id:
        return "Send was not executed: lead_id is missing from the approval payload."
    lead = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.id == UUID(str(lead_id)), Lead.deleted_at.is_(None)))
    enrollment_id = payload.get("enrollment_id")
    enrollment = None
    if enrollment_id:
        enrollment = db.scalar(
            select(SequenceEnrollment).where(
                SequenceEnrollment.tenant_id == tenant_id,
                SequenceEnrollment.id == UUID(str(enrollment_id)),
                SequenceEnrollment.deleted_at.is_(None),
            )
        )
        if enrollment is not None and lead is None:
            lead = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.id == enrollment.lead_id))
    if lead is None:
        return "Send was not executed: lead is missing from the approval payload."
    try:
        assert_can_email(lead)
    except HTTPException:
        reason = email_block_reason(lead) or "consent or suppression blocked the message"
        return f"Send was not executed: {reason}."
    if is_entity_paused(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id)):
        return "Send was not executed: automation is paused for this lead."
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    if in_quiet_hours(settings):
        return "Send deferred: quiet hours."
    limit = outreach_limit_reason(db, settings, lead.id)
    if limit:
        return f"Send was not executed: {limit}."
    provider = get_email_provider(db, tenant_id)
    health = provider.health()
    if not health.connected:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="email_blocked_config",
            next_action="connect_gmail",
            blocked_reason="BLOCKED BY CONFIGURATION",
            run_id=approval.run_id,
        )
        return "BLOCKED BY CONFIGURATION"
    if enrollment is None and payload.get("sequence_id"):
        sequence = db.scalar(
            select(Sequence).where(
                Sequence.tenant_id == tenant_id,
                Sequence.id == UUID(str(payload["sequence_id"])),
                Sequence.deleted_at.is_(None),
            )
        )
        if sequence is not None:
            enrollment = enroll_sequence(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                sequence=sequence,
                lead=lead,
                run_id=approval.run_id,
                actor_type="ai",
            )
            payload["enrollment_id"] = str(enrollment.id)
            approval.payload_json = json.dumps(payload, default=str)
    send_key = f"email.send:{tenant_id}:{approval.id}"
    claimed, key_row = claim_key(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        key=send_key,
        workflow="email_send",
        entity_id=str(lead.id),
        action_type="email.send",
    )
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="email.send",
        idempotency_key=send_key,
        provider=health.provider,
        approval_id=approval.id,
        entity_type="lead",
        entity_id=str(lead.id),
        request_summary=f"send:{lead.email}",
    )
    action.policy_version = current_policy_version(db, tenant_id)
    action.provider_mode = "MOCK" if health.is_mock else "LIVE"
    if action.status == "CONFIRMED" and action.external_id:
        return f"Provider {action.provider} recorded send {action.external_id}."
    replay = persisted_send_for_approval(db, tenant_id, approval.id)
    if replay is not None and replay.status == "SENT":
        confirm_action(action, provider=replay.provider, external_id=replay.provider_message_id, response_summary="replay")
        return f"Provider {replay.provider} recorded send {replay.provider_message_id}."
    if not claimed:
        if key_row.result_ref and replay is not None:
            confirm_action(action, provider=replay.provider, external_id=replay.provider_message_id, response_summary="replay")
            return f"Provider {replay.provider} recorded send {replay.provider_message_id}."
        return "Send already in progress for this approval."
    if not claim_daily_slot(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        kind="email",
        limit=settings.max_emails_per_day,
    ):
        return "Send was not executed: Daily email cap reached."
    subject = str(payload.get("subject") or "Follow-up")
    body = str(payload.get("body") or payload.get("template") or "")
    pending_id = f"pending-{uuid4()}"
    conversation = find_or_create_thread(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        lead=lead,
        subject=subject,
        provider=health.provider,
        is_mock=health.is_mock,
        thread_id=str(payload.get("thread_id") or ""),
    )
    message = existing or EmailMessage(
        tenant_id=tenant_id,
        created_by=actor_id,
        conversation_id=conversation.id,
        direction="outbound",
        from_addr="",
        to_addrs=json.dumps([lead.email]),
        subject=subject,
        body_text=body,
        provider=health.provider,
        provider_message_id=pending_id,
        provider_thread_id=conversation.provider_thread_id,
        status="SENDING",
        approval_id=approval.id,
        lead_id=lead.id,
        attempt=(existing.attempt + 1) if existing else 1,
    )
    if existing is None:
        db.add(message)
        db.flush()
    else:
        message.status = "SENDING"
        message.subject = subject
        message.body_text = body
    result = provider.send(to=lead.email, subject=subject, body=body, thread_id=conversation.provider_thread_id)
    if not result.ok:
        fail_action(action, failure_class="TRANSIENT" if result.retryable else "PERMANENT", error=result.reason, retryable=result.retryable)
        message.status = "RETRYING" if result.retryable else "FAILED"
        message.last_error = result.reason
        message.next_retry_at = datetime.now(UTC) + timedelta(minutes=2 ** min(message.attempt, 6)) if result.retryable else None
        if not result.retryable:
            upsert_state(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entity_type="lead",
                entity_id=str(lead.id),
                state="BLOCKED",
                last_action="email_failed",
                next_action="retry_send",
                blocked_reason=result.reason or "BLOCKED BY CONFIGURATION",
                run_id=approval.run_id,
            )
        return result.reason or "Send failed."
    confirm_action(action, provider=result.provider, external_id=result.provider_message_id, response_summary=result.reason)
    message.status = "SENT"
    message.provider = result.provider
    message.provider_message_id = result.provider_message_id
    message.provider_thread_id = result.thread_id
    message.sent_at = datetime.now(UTC)
    message.last_error = ""
    conversation.provider_thread_id = result.thread_id
    conversation.provider = result.provider
    conversation.is_mock = result.is_mock
    conversation.status = "sent"
    conversation.outcome = "sent"
    conversation.transcript = ((conversation.transcript or "") + f"\n\nOutbound: {body}").strip()
    conversation.summary = f"Last outbound via {result.provider}"
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="email",
        title=f"Email sent through {result.provider}",
        body=f"{result.reason} id={result.provider_message_id}",
        actor_type="ai",
    )
    upsert_state(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        state="CONTACTED",
        last_action="email_sent",
        next_action="wait_for_reply",
        blocked_reason="",
        run_id=approval.run_id,
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="email.sent",
        entity_type="lead",
        entity_id=str(lead.id),
        payload={
            "approval_id": str(approval.id),
            "message_id": str(message.id),
            "provider_message_id": result.provider_message_id,
            "provider": result.provider,
            "is_mock": result.is_mock,
        },
    )
    if enrollment is not None:
        advance_enrollment(db, enrollment)
    if approval.run_id:
        run = db.get(AutonomousRun, approval.run_id)
        if run is not None and run.tenant_id == tenant_id:
            run.status = "completed"
            run.summary = (run.summary + f" Email send executed via {result.provider}.").strip()
    remember_result(key_row, str(message.id))
    return f"Provider {result.provider} recorded send {result.provider_message_id}."


def retry_retrying_sends(db: Session, *, limit: int = 25) -> int:
    now = datetime.now(UTC)
    rows = db.scalars(
        select(EmailMessage)
        .where(
            EmailMessage.deleted_at.is_(None),
            EmailMessage.status == "RETRYING",
            EmailMessage.approval_id.is_not(None),
            EmailMessage.next_retry_at.is_not(None),
            EmailMessage.next_retry_at <= now,
        )
        .limit(limit)
    ).all()
    count = 0
    for row in rows:
        approval = db.get(AIApproval, row.approval_id)
        if approval is None or approval.tenant_id != row.tenant_id:
            continue
        execute_email_send(db, tenant_id=row.tenant_id, actor_id=row.created_by or approval.created_by, approval=approval)
        count += 1
    return count
