import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.signals import CustomerSignal, SupportSnapshot
from app.services.autopilot_settings import get_or_create_settings
from app.services.entity_mapping import resolve_customer
from app.services.intelligence_state import mark_dirty, touch_watermark
from app.services.provider_metrics import SUPPORT_EVENTS
from app.services.usage_ingest import _parse_dt, aware_dt, freshness_state

SUPPORT_EVENT_TYPES = {
    "ticket.created",
    "ticket.closed",
    "ticket.resolved",
    "ticket.escalated",
    "ticket.reopened",
    "ticket.severity_changed",
    "ticket.deleted",
    "ticket.voided",
}


def latest_support(db: Session, tenant_id: UUID, customer_id: UUID) -> SupportSnapshot | None:
    return db.scalar(
        select(SupportSnapshot)
        .where(
            SupportSnapshot.tenant_id == tenant_id,
            SupportSnapshot.customer_id == customer_id,
            SupportSnapshot.deleted_at.is_(None),
        )
        .order_by(SupportSnapshot.last_event_at.desc())
    )


def customer_support_metrics(db: Session, tenant_id: UUID, customer_id: UUID) -> dict:
    rows = db.scalars(
        select(SupportSnapshot).where(
            SupportSnapshot.tenant_id == tenant_id,
            SupportSnapshot.customer_id == customer_id,
            SupportSnapshot.deleted_at.is_(None),
        )
    ).all()
    open_rows = [row for row in rows if row.status in {"open", "pending", "escalated"}]
    critical = [row for row in open_rows if row.severity.lower() in {"critical", "sev1", "p1", "high"}]
    since = datetime.now(UTC) - timedelta(days=30)
    recent = [
        row
        for row in rows
        if aware_dt(row.opened_at) is not None and aware_dt(row.opened_at) >= since
    ]
    resolved = [row for row in rows if row.resolved_at and row.opened_at]
    hours = []
    for row in resolved:
        opened = aware_dt(row.opened_at)
        closed = aware_dt(row.resolved_at)
        if opened is None or closed is None:
            continue
        hours.append(max(int((closed - opened).total_seconds() // 3600), 0))
    last = max((aware_dt(row.last_event_at) for row in rows if row.last_event_at), default=None)
    return {
        "open_total": len(open_rows),
        "open_critical": len(critical),
        "tickets_30d": len(recent),
        "avg_resolution_hours": int(sum(hours) / len(hours)) if hours else None,
        "escalations": sum(1 for row in rows if row.escalated),
        "last_event_at": last,
    }


def ingest_support_payload(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    payload: dict,
    external_id: str,
) -> str:
    event_type = str(payload.get("event_type") or payload.get("type") or "ticket.created")
    ticket_id = str(payload.get("ticket_id") or payload.get("external_id") or external_id)
    customer = resolve_customer(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        provider="support",
        payload={**payload, "ticket_external_id": ticket_id},
    )
    existing = db.scalar(
        select(SupportSnapshot).where(
            SupportSnapshot.tenant_id == tenant_id,
            SupportSnapshot.external_id == ticket_id,
            SupportSnapshot.deleted_at.is_(None),
        )
    )
    if existing is not None and event_type == "ticket.created" and existing.status != "void":
        return "duplicate"
    observed = _parse_dt(payload.get("observed_at") or payload.get("opened_at"))
    status = str(payload.get("status") or "open")
    if event_type in {"ticket.closed", "ticket.resolved"}:
        status = "resolved"
    if event_type in {"ticket.deleted", "ticket.voided"}:
        status = "void"
    if event_type == "ticket.escalated":
        status = "escalated"
    if event_type == "ticket.reopened":
        status = "open"
    severity = str(payload.get("severity") or payload.get("priority") or "")
    if customer is None:
        SUPPORT_EVENTS.labels(provider="support").inc()
        return "unmapped"
    if existing is None:
        existing = SupportSnapshot(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=customer.id,
            account_id=customer.account_id,
            provider="support",
            external_id=ticket_id,
            opened_at=observed,
        )
        db.add(existing)
    existing.status = status
    existing.severity = severity or existing.severity
    existing.sentiment = str(payload.get("sentiment") or existing.sentiment)
    existing.escalated = existing.escalated or event_type == "ticket.escalated"
    existing.reopened = existing.reopened or event_type == "ticket.reopened"
    if status in {"resolved", "closed", "void"}:
        existing.resolved_at = _parse_dt(payload.get("resolved_at") or datetime.now(UTC))
    existing.last_event_at = datetime.now(UTC)
    db.flush()
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    settings.support_live_enabled = True
    metrics = customer_support_metrics(db, tenant_id, customer.id)
    existing.open_total = metrics["open_total"]
    existing.open_critical = metrics["open_critical"]
    existing.tickets_30d = metrics["tickets_30d"]
    existing.avg_resolution_hours = metrics["avg_resolution_hours"]
    existing.escalations = metrics["escalations"]
    existing.freshness_state = freshness_state(existing.last_event_at, settings.support_freshness_hours)
    existing.is_mock = False
    existing.evidence = f"ticket {ticket_id} {status} severity={existing.severity}"
    bounded = json.dumps({key: payload.get(key) for key in list(payload)[:20]}, default=str)[:4000]
    db.add(
        CustomerSignal(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=customer.id,
            account_id=customer.account_id,
            signal_type=event_type,
            signal_category="SUPPORT",
            source_provider="support",
            external_reference=f"{ticket_id}:{event_type}:{external_id}",
            value_text=status,
            value_json=bounded,
            observed_at=observed,
            received_at=datetime.now(UTC),
            freshness_state="LIVE",
            is_mock=False,
            is_verified=True,
        )
    )
    db.flush()
    SUPPORT_EVENTS.labels(provider="support").inc()
    mark_dirty(db, tenant_id=tenant_id, actor_id=actor_id, customer_id=customer.id)
    touch_watermark(db, tenant_id=tenant_id, provider="support", cursor=external_id)
    return "ingested"
