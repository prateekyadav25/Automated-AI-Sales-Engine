import json
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings as current_settings
from app.models.ai import AIApproval
from app.models.crm import Lead, Renewal
from app.models.lifecycle import Campaign
from app.models.signals import ExternalEntityMapping
from app.services.ads import execute_ads_creative, execute_ads_pause, execute_ads_spend
from app.services.automation_state import pause_entity, upsert_state
from app.services.autopilot_settings import get_or_create_settings
from app.services.calendar_booking import book_meeting, cancel_meeting, reschedule_meeting
from app.services.email_send import execute_email_send
from app.services.entity_mapping import confirm_mapping
from app.services.expansion import mint_opportunity
from app.services.meeting_capture import grant_recording_consent
from app.services.renewal import execute_renewal_commercial
from app.services.voice import execute_voice_dial
from app.services.whatsapp_send import execute_whatsapp_send

Handler = Callable[..., str]


def _payload(row: AIApproval) -> dict:
    try:
        data = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _ads_launch(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    _ = payload_patch
    return execute_ads_spend(db, tenant_id=tenant_id, actor_id=actor_id, approval=row)


def _ads_pause(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    _ = payload_patch
    return execute_ads_pause(db, tenant_id=tenant_id, actor_id=actor_id, approval=row)


def _ads_creative(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    _ = payload_patch
    return execute_ads_creative(db, tenant_id=tenant_id, actor_id=actor_id, approval=row)


def _voice_dial(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    _ = payload_patch
    return execute_voice_dial(db, tenant_id=tenant_id, actor_id=actor_id, approval=row)


def _meeting_record(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    _ = (actor_id, payload_patch)
    payload = _payload(row)
    meeting_id = payload.get("meeting_id") or row.entity_id
    meeting = grant_recording_consent(db, tenant_id=tenant_id, meeting_id=UUID(str(meeting_id)))
    return f"Recording consent granted for meeting {meeting.id}."


def _expansion(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    _ = payload_patch
    rec_id = _payload(row).get("recommendation_id")
    if not rec_id:
        return "Expansion recommendation id is missing."
    minted = mint_opportunity(db, tenant_id=tenant_id, actor_id=actor_id, recommendation_id=UUID(str(rec_id)))
    return f"Expansion opportunity {minted.id} created." if minted else "Expansion recommendation was not found."


def _renewal(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    _ = payload_patch
    return execute_renewal_commercial(db, tenant_id=tenant_id, actor_id=actor_id, approval=row)


def _send(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    if row.entity_type == "customer":
        return "Customer communication approved. A mapped contact email is required before provider send."
    return execute_email_send(db, tenant_id=tenant_id, actor_id=actor_id, approval=row, payload_patch=payload_patch)


def _calendar_book(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    payload = {**_payload(row), **(payload_patch or {})}
    return book_meeting(db, tenant_id=tenant_id, actor_id=actor_id, approval=row, payload=payload)


def _calendar_reschedule(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    payload = {**_payload(row), **(payload_patch or {})}
    return reschedule_meeting(db, tenant_id=tenant_id, actor_id=actor_id, approval=row, payload=payload)


def _calendar_cancel(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    payload = {**_payload(row), **(payload_patch or {})}
    return cancel_meeting(db, tenant_id=tenant_id, actor_id=actor_id, approval=row, payload=payload)


def _whatsapp(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    _ = payload_patch
    return execute_whatsapp_send(db, tenant_id=tenant_id, actor_id=actor_id, approval=row)


def _mapping_confirm(db: Session, *, tenant_id: UUID, actor_id: UUID, row: AIApproval, payload_patch: dict | None = None) -> str:
    payload = {**_payload(row), **(payload_patch or {})}
    mapping_id = payload.get("mapping_id") or row.entity_id
    mapping = db.get(ExternalEntityMapping, UUID(str(mapping_id)))
    if mapping is None or mapping.tenant_id != tenant_id:
        return "Mapping was not found."
    confirm_mapping(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        mapping=mapping,
        internal_entity_type=str(payload.get("internal_entity_type") or mapping.internal_entity_type),
        internal_entity_id=str(payload.get("internal_entity_id") or mapping.internal_entity_id),
    )
    return f"Mapping {mapping.external_id} confirmed."


HANDLERS: dict[str, Handler] = {
    "ads.spend": _ads_launch,
    "ads.launch": _ads_launch,
    "ads.pause": _ads_pause,
    "ads.creative": _ads_creative,
    "meeting.record": _meeting_record,
    "voice.dial": _voice_dial,
    "expansion.opportunity.create": _expansion,
    "renewal.commercial": _renewal,
    "calendar.create": _calendar_book,
    "calendar.book": _calendar_book,
    "calendar.reschedule": _calendar_reschedule,
    "calendar.cancel": _calendar_cancel,
    "mapping.confirm": _mapping_confirm,
    "whatsapp.send": _whatsapp,
}


def _stale_reason(db: Session, tenant_id: UUID, row: AIApproval) -> str:
    payload = _payload(row)
    if row.entity_type == "lead" and row.entity_id:
        lead = db.get(Lead, UUID(row.entity_id))
        if lead is not None and lead.tenant_id == tenant_id and lead.opt_out:
            return "Lead has opted out. Execution refused."
    if row.action_type.startswith("renewal."):
        renewal_id = payload.get("renewal_id") or row.entity_id
        if renewal_id:
            renewal = db.get(Renewal, UUID(str(renewal_id)))
            if renewal is not None and renewal.status in {"renewed", "completed", "won"}:
                return "Renewal is already completed. Execution refused."
    if row.action_type.startswith("ads."):
        campaign_id = payload.get("campaign_id")
        if campaign_id:
            campaign = db.get(Campaign, UUID(str(campaign_id)))
            if campaign is not None and campaign.status in {"cancelled", "canceled", "paused"}:
                return "Campaign is cancelled. Execution refused."
    return ""


def _channel_blocked(db: Session, tenant_id: UUID, action: str) -> str:
    if current_settings().global_emergency_stop:
        return "Global emergency stop is active. External actions are suspended."
    settings = get_or_create_settings(db, tenant_id=tenant_id)
    if settings.emergency_stop:
        return "Emergency stop is active. External actions are suspended."
    if action.endswith(".send") and settings.email_channel_paused:
        return "Email channel is paused."
    if action.startswith("ads.") and settings.ads_channel_paused:
        return "Ads channel is paused."
    if action.startswith("voice.") and settings.voice_channel_paused:
        return "Voice channel is paused."
    if action.startswith("discovery.") and settings.discovery_channel_paused:
        return "Discovery channel is paused."
    if action.startswith("whatsapp.") and settings.whatsapp_channel_paused:
        return "WhatsApp channel is paused."
    return ""


def dispatch_approval(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    row: AIApproval,
    payload_patch: dict | None = None,
) -> str:
    from datetime import UTC, datetime

    blocked = _channel_blocked(db, tenant_id, row.action_type)
    if blocked:
        return blocked
    if row.expires_at is not None:
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < datetime.now(UTC):
            row.status = "expired"
            return "Approval expired before execution."
    stale = _stale_reason(db, tenant_id, row)
    if stale:
        return stale
    action = row.action_type
    handler = HANDLERS.get(action)
    if handler is not None:
        return handler(db, tenant_id=tenant_id, actor_id=actor_id, row=row, payload_patch=payload_patch)
    if action.endswith(".send"):
        return _send(db, tenant_id=tenant_id, actor_id=actor_id, row=row, payload_patch=payload_patch)
    return ""


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
        if row.status != "pending":
            return
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
    if row.status not in {"pending", "approved"}:
        return
    if row.status == "pending":
        row.status = "approved"
        row.decided_by = actor_id
    executed = dispatch_approval(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        row=row,
        payload_patch=payload_patch,
    )
    row.decision_note = ((note + " ").strip() + " " + executed).strip()
