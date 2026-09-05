from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.crm import Account, Lead
from app.services.audit import emit_event
from app.services.crm import add_activity
from app.services.market import refresh_account_intelligence


def enrich_lead(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    correlation_id: str = "",
) -> dict:
    account = db.get(Account, lead.account_id) if lead.account_id else None
    created = {"account_signals": 0, "intent_signals": 0, "technology_signals": 0, "triggers": 0}
    source = "none"
    if account is not None:
        created = refresh_account_intelligence(db, tenant_id=tenant_id, actor_id=actor_id, account=account)
        source = "mock-intelligence"
    provenance = {
        "source": source,
        "confidence": 55 if account is not None else 20,
        "verified_at": datetime.now(UTC).isoformat(),
        "created": created,
        "overwrote_fields": [],
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
