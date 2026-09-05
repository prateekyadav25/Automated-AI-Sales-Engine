import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.autonomy import AutonomousRun
from app.models.crm import Lead
from app.models.lifecycle import Conversation, Sequence, SequenceEnrollment
from app.providers.email import get_email_provider
from app.services.ads import execute_ads_spend
from app.services.audit import emit_event
from app.services.automation_state import pause_entity, upsert_state
from app.services.crm import add_activity
from app.services.lifecycle import enroll_sequence
from app.services.voice import execute_voice_dial


def _payload(row: AIApproval) -> dict:
    try:
        data = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


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
    lead_id = payload.get("lead_id") or approval.entity_id
    lead = None
    if lead_id:
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
    if lead.opt_out or not lead.consent_email:
        return "Send was not executed: consent or suppression blocked the message."
    if enrollment is None and payload.get("sequence_id"):
        sequence = db.scalar(
            select(Sequence).where(
                Sequence.tenant_id == tenant_id,
                Sequence.id == UUID(str(payload["sequence_id"])),
                Sequence.deleted_at.is_(None),
            )
        )
        if sequence is not None:
            run_id = approval.run_id
            enrollment = enroll_sequence(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                sequence=sequence,
                lead=lead,
                run_id=run_id,
                actor_type="ai",
            )
            payload["enrollment_id"] = str(enrollment.id)
            approval.payload_json = json.dumps(payload, default=str)
    provider = get_email_provider()
    result = provider.send(
        to=lead.email,
        subject=str(payload.get("subject") or "Follow-up"),
        body=str(payload.get("body") or payload.get("template") or ""),
    )
    conversation = Conversation(
        tenant_id=tenant_id,
        created_by=actor_id,
        channel="email",
        account_id=lead.account_id,
        contact_id=lead.contact_id,
        subject=str(payload.get("subject") or "Follow-up"),
        status="sent",
        outcome="sent",
        consent=True,
        provider=result.provider,
        is_mock=result.is_mock,
        transcript=str(payload.get("body") or payload.get("template") or ""),
        summary=f"provider_message_id={result.provider_message_id} thread_id={result.thread_id}",
    )
    db.add(conversation)
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="email",
        title="Email sent",
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
            "provider_message_id": result.provider_message_id,
            "provider": result.provider,
            "is_mock": result.is_mock,
        },
    )
    if approval.run_id:
        run = db.get(AutonomousRun, approval.run_id)
        if run is not None and run.tenant_id == tenant_id:
            run.status = "completed"
            run.summary = (run.summary + " Email send executed via mock provider.").strip()
    return f"Provider {result.provider} recorded send {result.provider_message_id}."


def apply_approval_decision(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    row: AIApproval,
    decision: str,
    note: str,
    payload_patch: dict | None = None,
    pause_automation: bool = False,
) -> None:
    entity_type = row.entity_type or _payload(row).get("entity_type") or ""
    entity_id = row.entity_id or _payload(row).get("lead_id") or ""
    if pause_automation and entity_type and entity_id:
        pause_entity(db, tenant_id=tenant_id, actor_id=actor_id, entity_type=str(entity_type), entity_id=str(entity_id))
    if decision == "reject":
        row.status = "rejected"
        row.decision_note = note
        row.decided_by = actor_id
        if entity_type == "lead" and entity_id:
            upsert_state(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entity_type="lead",
                entity_id=str(entity_id),
                state="BLOCKED",
                last_action="approval_rejected",
                blocked_reason=note or "Rejected in Approval Center",
                run_id=row.run_id,
            )
        return
    row.status = "approved"
    row.decided_by = actor_id
    if row.action_type == "ads.spend":
        row.decision_note = ((note + " ").strip() + " " + execute_ads_spend(db, tenant_id=tenant_id, approval=row)).strip()
        return
    if row.action_type == "voice.dial":
        row.decision_note = (
            (note + " ").strip() + " " + execute_voice_dial(db, tenant_id=tenant_id, actor_id=actor_id, approval=row)
        ).strip()
        return
    if row.action_level >= 2 and row.action_type.endswith(".send"):
        row.decision_note = (
            (note + " ").strip()
            + " "
            + execute_email_send(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                approval=row,
                payload_patch=payload_patch,
            )
        ).strip()
        return
    row.decision_note = note
