import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.models.crm import Activity, Customer
from app.models.lifecycle import HealthScore, MeetingRecord
from app.models.post_sale import CustomerRisk, ExpansionRecommendation
from app.services.ai_artifacts import fingerprint, reuse_or_none, upsert_artifact
from app.services.audit import emit_event
from app.services.crm import add_activity

CADENCE_DAYS = {"monthly": 30, "quarterly": 90, "semiannual": 180}


def next_qbr_date(customer: Customer, today: date | None = None) -> date:
    today = today or date.today()
    days = CADENCE_DAYS.get((customer.qbr_cadence or "quarterly").lower(), 90)
    if customer.next_qbr_at and customer.next_qbr_at >= today:
        return customer.next_qbr_at
    return today + timedelta(days=days)


def qbr_period(when: date) -> str:
    quarter = (when.month - 1) // 3 + 1
    return f"{when.year}-Q{quarter}"


def prepare_qbr(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer) -> dict:
    due = next_qbr_date(customer)
    customer.next_qbr_at = due
    period = qbr_period(due)
    health = db.scalar(select(HealthScore).where(HealthScore.tenant_id == tenant_id, HealthScore.customer_id == customer.id, HealthScore.deleted_at.is_(None)))
    risks = db.scalars(
        select(CustomerRisk).where(CustomerRisk.tenant_id == tenant_id, CustomerRisk.customer_id == customer.id, CustomerRisk.status == "open")
    ).all()
    meetings = db.scalars(
        select(MeetingRecord)
        .where(MeetingRecord.tenant_id == tenant_id, MeetingRecord.account_id == customer.account_id, MeetingRecord.deleted_at.is_(None))
        .order_by(MeetingRecord.created_at.desc())
        .limit(8)
    ).all()
    expansion = db.scalars(
        select(ExpansionRecommendation).where(
            ExpansionRecommendation.tenant_id == tenant_id,
            ExpansionRecommendation.customer_id == customer.id,
            ExpansionRecommendation.status == "open",
        )
    ).all()
    evidence = {
        "period": period,
        "lifecycle": customer.lifecycle_state,
        "health": health.total if health else None,
        "health_trend": customer.health_trend,
        "unavailable": health.unavailable_components if health else "",
        "risks": [row.risk_type for row in risks],
        "meetings": [row.title for row in meetings],
        "expansion": [row.title for row in expansion],
        "arr": str(customer.arr) if customer.arr else None,
        "roi": None,
    }
    source = fingerprint(evidence)
    reused = reuse_or_none(db, tenant_id=tenant_id, kind="qbr", entity_type="customer", entity_id=f"{customer.id}:{period}", source_fingerprint=source)
    if reused is None:
        llm = get_llm_provider()
        result = llm.complete(
            json.dumps(evidence, default=str),
            system=(
                "You are QBRAgent. Prepare a QBR brief from persisted evidence only. "
                "Do not invent ROI, ARR, usage, or quotes. Unknown stays null. Recommend an agenda."
            ),
        )
        reused = upsert_artifact(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            kind="qbr",
            entity_type="customer",
            entity_id=f"{customer.id}:{period}",
            title=f"QBR {period}",
            content={"brief": result.text, "evidence": evidence},
            source_fingerprint=source,
            provider=result.provider,
            is_mock=result.is_mock,
        )
        text = result.text
    else:
        try:
            text = json.loads(reused.content_json).get("brief") or reused.content_json
        except json.JSONDecodeError:
            text = reused.content_json
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="qbr.prepared",
        entity_type="customer",
        entity_id=str(customer.id),
        payload={"period": period, "due": due.isoformat()},
    )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="customer",
        entity_id=str(customer.id),
        activity_type="qbr",
        title=f"QBR brief prepared for {period}",
        body="Quantitative claims come from persisted data only.",
        actor_type="ai",
    )
    _ = Activity, datetime, UTC
    return {"period": period, "brief": text, "due": due.isoformat()}
