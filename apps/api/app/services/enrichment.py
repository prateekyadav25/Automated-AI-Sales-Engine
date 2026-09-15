from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.crm import Account, Lead
from app.providers.enrichment import get_enrichment_provider
from app.services.audit import emit_event, write_audit
from app.services.crm import add_activity
from app.services.market import refresh_account_intelligence
from app.services.query import get_owned


def enrich_lead(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    correlation_id: str = "",
    domain: str = "",
) -> dict:
    account = db.get(Account, lead.account_id) if lead.account_id else None
    created = {"account_signals": 0, "intent_signals": 0, "technology_signals": 0, "triggers": 0}
    source = "none"
    if account is not None:
        created = refresh_account_intelligence(db, tenant_id=tenant_id, actor_id=actor_id, account=account)
        source = "mock-intelligence"
    email_result = {"ok": False, "email": lead.email, "verified": False, "reason": "", "provider": "", "is_mock": True}
    host = domain or (lead.email.split("@", 1)[1] if "@" in (lead.email or "") else "")
    if host:
        provider = get_enrichment_provider(db, tenant_id)
        found = provider.find_email(
            first_name=lead.first_name,
            last_name=lead.last_name,
            domain=host,
            company_name=lead.company_name,
        )
        email_result = {
            "ok": found.ok,
            "email": found.email or lead.email,
            "verified": False,
            "reason": found.reason,
            "provider": found.provider,
            "is_mock": found.is_mock,
        }
        if found.ok and found.email and not lead.email:
            lead.email = found.email
        if found.ok and (found.email or lead.email):
            check = provider.verify_email(email=found.email or lead.email)
            email_result["verified"] = check.verified
            email_result["reason"] = check.reason or found.reason
    provenance = {
        "source": source,
        "confidence": 55 if account is not None else 20,
        "verified_at": datetime.now(UTC).isoformat(),
        "created": created,
        "overwrote_fields": [],
        "email": email_result,
    }
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="enrichment",
        title="Lead enriched",
        body=f"Provenance {source}. Existing CRM values were not overwritten.",
        actor_type="ai",
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="lead.enriched",
        entity_type="lead",
        entity_id=str(lead.id),
        payload=provenance,
        correlation_id=correlation_id,
    )
    return provenance


def enrich_owned_lead(db: Session, *, tenant_id: UUID, actor_id: UUID, lead_id: UUID, domain: str = "") -> dict:
    lead = get_owned(db, Lead, tenant_id, lead_id)
    result = enrich_lead(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, domain=domain)
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="lead.enrich",
        entity_type="lead",
        entity_id=str(lead.id),
        after={"source": result.get("source"), "email": result.get("email")},
    )
    return result
