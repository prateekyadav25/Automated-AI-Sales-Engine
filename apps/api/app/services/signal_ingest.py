from uuid import UUID

from sqlalchemy.orm import Session

from app.models.integrations import ProviderInboxEvent
from app.services.customer_intelligence import refresh_customer_intelligence
from app.services.entity_mapping import resolve_customer
from app.services.finance_ingest import ingest_finance_payload
from app.services.provider_metrics import CUSTOMER_SIGNALS
from app.services.support_ingest import ingest_support_payload
from app.services.usage_ingest import ingest_usage_payload

SIGNAL_PROVIDERS = {"usage", "support", "finance", "erp"}


def ingest_provider_payload(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    provider: str,
    payload: dict,
    external_id: str,
) -> str:
    normalized = provider.strip().lower()
    if normalized == "usage":
        result = ingest_usage_payload(db, tenant_id=tenant_id, actor_id=actor_id, payload=payload, external_id=external_id)
    elif normalized == "support":
        result = ingest_support_payload(db, tenant_id=tenant_id, actor_id=actor_id, payload=payload, external_id=external_id)
    elif normalized in {"finance", "erp"}:
        result = ingest_finance_payload(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            payload=payload,
            external_id=external_id,
            provider=normalized,
        )
    else:
        return "ignored"
    if result == "ingested":
        CUSTOMER_SIGNALS.labels(provider=normalized).inc()
        customer = resolve_customer(db, tenant_id=tenant_id, actor_id=actor_id, provider=normalized, payload=payload)
        if customer is not None:
            refresh_customer_intelligence(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer)
    return result


def ingest_inbox_event(db: Session, event: ProviderInboxEvent, *, actor_id: UUID, payload: dict) -> str:
    return ingest_provider_payload(
        db,
        tenant_id=event.tenant_id,
        actor_id=actor_id,
        provider=event.provider,
        payload=payload if isinstance(payload, dict) else {},
        external_id=event.external_id,
    )
