from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.crm import Contact, Lead
from app.models.pilot import WhatsAppTemplate
from app.providers.whatsapp import get_whatsapp_provider
from app.services.consent import whatsapp_block_reason as consent_whatsapp_block
from app.services.policy_versions import current_policy_version
from app.services.provider_ops import begin_action, confirm_action, fail_action


def whatsapp_block_reason(lead: Lead | None, contact: Contact | None) -> str | None:
    return consent_whatsapp_block(lead, contact)


def execute_whatsapp_send(db: Session, *, tenant_id: UUID, actor_id: UUID, approval: AIApproval) -> str:
    payload = json.loads(approval.payload_json or "{}")
    template_id = str(payload.get("template_id") or "")
    language = str(payload.get("language") or "en")
    to = str(payload.get("to") or "")
    lead = db.get(Lead, UUID(approval.entity_id)) if approval.entity_type == "lead" and approval.entity_id else None
    blocked = whatsapp_block_reason(lead, None)
    if blocked:
        return blocked
    template = db.scalar(
        select(WhatsAppTemplate).where(
            WhatsAppTemplate.tenant_id == tenant_id,
            WhatsAppTemplate.template_id == template_id,
            WhatsAppTemplate.language == language,
            WhatsAppTemplate.deleted_at.is_(None),
        )
    )
    if template is None or template.status != "approved":
        return "Approved WhatsApp template is required"
    if not to:
        return "WhatsApp destination is required. Email is not used as a WhatsApp address."
    key = f"whatsapp.send:{tenant_id}:{approval.id}"
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="whatsapp.send",
        idempotency_key=key,
        provider="whatsapp",
        approval_id=approval.id,
        entity_type=approval.entity_type,
        entity_id=approval.entity_id,
    )
    action.policy_version = current_policy_version(db, tenant_id)
    if action.status == "CONFIRMED":
        return f"WhatsApp already sent {action.external_id}"
    result = get_whatsapp_provider().send_template(
        to=to,
        template_id=template_id,
        language=language,
        variables=payload.get("variables") or {},
    )
    if not result.ok:
        fail_action(action, failure_class="CONFIGURATION", error=result.error, retryable=False)
        return result.error or "WhatsApp is NOT_CONFIGURED"
    confirm_action(action, provider=result.provider, external_id=result.external_id, response_summary=result.status)
    return f"WhatsApp {result.status} {result.external_id}"
