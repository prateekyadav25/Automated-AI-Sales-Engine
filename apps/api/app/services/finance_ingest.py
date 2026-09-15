import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Customer, Task
from app.models.post_sale import Contract
from app.models.signals import CustomerSignal, FinanceSnapshot
from app.services.audit import emit_event
from app.services.autopilot_settings import get_or_create_settings
from app.services.entity_mapping import resolve_customer
from app.services.intelligence_state import mark_dirty, touch_watermark
from app.services.provider_metrics import FINANCE_EVENTS
from app.services.usage_ingest import _parse_dt, freshness_state

FINANCE_EVENT_TYPES = {
    "invoice.created",
    "invoice.paid",
    "invoice.overdue",
    "invoice.voided",
    "payment.received",
    "subscription.started",
    "subscription.changed",
    "credit.hold",
    "refund.issued",
}
ERP_EVENT_TYPES = {
    "subscription.started",
    "subscription.changed",
    "customer.commercial_updated",
}


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def latest_finance(db: Session, tenant_id: UUID, customer_id: UUID) -> FinanceSnapshot | None:
    return db.scalar(
        select(FinanceSnapshot)
        .where(
            FinanceSnapshot.tenant_id == tenant_id,
            FinanceSnapshot.customer_id == customer_id,
            FinanceSnapshot.deleted_at.is_(None),
        )
        .order_by(FinanceSnapshot.last_event_at.desc())
    )


def _raise_mismatch(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, summary: str, evidence: dict) -> None:
    existing = db.scalar(
        select(Task).where(
            Task.tenant_id == tenant_id,
            Task.entity_type == "customer",
            Task.entity_id == str(customer.id),
            Task.title == "Review commercial data mismatch",
            Task.status == "open",
            Task.deleted_at.is_(None),
        )
    )
    if existing is not None:
        existing.description = summary
        return
    db.add(
        Task(
            tenant_id=tenant_id,
            created_by=actor_id,
            title="Review commercial data mismatch",
            description=summary,
            status="open",
            priority="high",
            entity_type="customer",
            entity_id=str(customer.id),
            source="workflow",
            owner_id=customer.csm_owner_id or customer.owner_id,
        )
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="commercial.mismatch",
        entity_type="customer",
        entity_id=str(customer.id),
        payload=evidence,
    )


def ingest_finance_payload(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    payload: dict,
    external_id: str,
    provider: str = "finance",
) -> str:
    event_type = str(payload.get("event_type") or payload.get("type") or "invoice.created")
    record_id = str(payload.get("invoice_id") or payload.get("subscription_id") or payload.get("external_id") or external_id)
    customer = resolve_customer(db, tenant_id=tenant_id, actor_id=actor_id, provider=provider, payload=payload)
    existing = db.scalar(
        select(FinanceSnapshot).where(
            FinanceSnapshot.tenant_id == tenant_id,
            FinanceSnapshot.provider == provider,
            FinanceSnapshot.external_id == record_id,
            FinanceSnapshot.deleted_at.is_(None),
        )
    )
    if existing is not None and event_type == "invoice.created":
        return "duplicate"
    if customer is None:
        FINANCE_EVENTS.labels(provider=provider).inc()
        return "unmapped"
    observed = _parse_dt(payload.get("observed_at") or payload.get("issued_at"))
    status = str(payload.get("status") or event_type.split(".")[-1])
    amount = _decimal(payload.get("amount") or payload.get("value"))
    currency = str(payload.get("currency") or "")
    if existing is None:
        existing = FinanceSnapshot(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=customer.id,
            account_id=customer.account_id,
            provider=provider,
            external_id=record_id,
        )
        db.add(existing)
    existing.record_type = str(payload.get("record_type") or ("subscription" if "subscription" in event_type else "invoice"))
    existing.status = status
    existing.currency = currency or existing.currency
    existing.amount = amount
    existing.outstanding_balance = _decimal(payload.get("outstanding_balance"))
    if existing.outstanding_balance is None and event_type == "invoice.overdue" and amount is not None:
        existing.outstanding_balance = amount
    if event_type == "invoice.paid" or event_type == "payment.received":
        existing.outstanding_balance = Decimal("0")
        existing.last_payment_at = observed
        existing.days_past_due = 0
    if event_type == "invoice.overdue":
        existing.days_past_due = int(payload.get("days_past_due") or 1)
        existing.overdue_count = int(payload.get("overdue_count") or 1)
    if event_type == "credit.hold":
        existing.credit_hold = True
    if event_type in {"invoice.voided", "refund.issued"}:
        existing.status = "void"
    existing.last_event_at = datetime.now(UTC)
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    if provider == "erp":
        settings.erp_live_enabled = True
    else:
        settings.finance_live_enabled = True
    hours = settings.finance_freshness_hours
    existing.freshness_state = freshness_state(existing.last_event_at, hours)
    existing.is_mock = False
    existing.evidence = f"{provider} {record_id} {status} amount={amount}"
    bounded = json.dumps({key: payload.get(key) for key in list(payload)[:20]}, default=str)[:4000]
    db.add(
        CustomerSignal(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=customer.id,
            account_id=customer.account_id,
            signal_type=event_type,
            signal_category="FINANCE" if provider == "finance" else "COMMERCIAL",
            source_provider=provider,
            external_reference=f"{record_id}:{event_type}:{external_id}",
            value_numeric=amount,
            value_text=status,
            value_json=bounded,
            observed_at=observed,
            received_at=datetime.now(UTC),
            freshness_state="LIVE",
            is_mock=False,
            is_verified=True,
        )
    )
    contract = db.scalar(
        select(Contract).where(
            Contract.tenant_id == tenant_id,
            Contract.customer_id == customer.id,
            Contract.deleted_at.is_(None),
        )
    )
    reported = _decimal(payload.get("contract_value") or payload.get("subscription_value"))
    if contract and reported is not None and contract.total_value is not None and reported != contract.total_value:
        _raise_mismatch(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            customer=customer,
            summary=f"Finance/ERP value {reported} does not match contract {contract.total_value}. Contract terms were not overwritten.",
            evidence={"contract_value": str(contract.total_value), "reported": str(reported), "code": "COMMERCIAL_DATA_MISMATCH"},
        )
    db.flush()
    FINANCE_EVENTS.labels(provider=provider).inc()
    mark_dirty(db, tenant_id=tenant_id, actor_id=actor_id, customer_id=customer.id)
    touch_watermark(db, tenant_id=tenant_id, provider=provider, cursor=external_id)
    return "ingested"
