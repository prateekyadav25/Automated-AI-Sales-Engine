import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.models.ai import AIApproval
from app.models.crm import Customer, Renewal, Task
from app.models.lifecycle import HealthScore
from app.models.post_sale import Contract, CustomerRisk
from app.services.ai_artifacts import fingerprint, reuse_or_none, upsert_artifact
from app.services.audit import emit_event
from app.services.crm import add_activity
from app.services.customer_lifecycle import set_lifecycle
from app.services.idempotency import claim_key


def parse_windows(raw: str) -> list[int]:
    days = []
    for part in (raw or "180,120,90,60,30").split(","):
        part = part.strip()
        if part.isdigit():
            days.append(int(part))
    return days or [180, 120, 90, 60, 30]


def commercial_baseline(contract: Contract | None, renewal: Renewal) -> tuple[Decimal | None, str]:
    if contract and contract.total_value is not None:
        if contract.escalation_pct is None:
            return contract.total_value, "needs_review"
        bump = Decimal(contract.escalation_pct) / Decimal(100)
        return (contract.total_value * (Decimal("1") + bump)).quantize(Decimal("0.01")), "calculated"
    if renewal.current_arr and renewal.current_arr > 0:
        return renewal.current_arr, "needs_review"
    return None, "needs_review"


def score_readiness(db: Session, *, tenant_id: UUID, customer: Customer, renewal: Renewal) -> dict:
    from app.services.finance_ingest import latest_finance
    from app.services.support_ingest import customer_support_metrics
    from app.services.usage_ingest import latest_rollup

    health = db.scalar(select(HealthScore).where(HealthScore.tenant_id == tenant_id, HealthScore.customer_id == customer.id, HealthScore.deleted_at.is_(None)))
    open_risks = db.scalars(
        select(CustomerRisk).where(CustomerRisk.tenant_id == tenant_id, CustomerRisk.customer_id == customer.id, CustomerRisk.status == "open")
    ).all()
    score = 40
    why_ready: list[str] = []
    why_risk: list[str] = []
    if health:
        score += min(health.total // 4, 25)
        if health.total >= 70:
            why_ready.append(f"Health {health.total} on {health.version}")
        if health.trend == "declining":
            why_risk.append("Health is declining")
            score -= 10
        if health.trend == "improving":
            score += 6
            why_ready.append("Health trend is improving")
        if getattr(health, "health_data_coverage", 0) >= 50:
            why_ready.append(f"Evidence coverage {health.health_data_coverage}%")
        else:
            why_risk.append(f"Evidence coverage {getattr(health, 'health_data_coverage', 0)}%")
    else:
        why_risk.append("No health score")
    rollup = latest_rollup(db, tenant_id, customer.id)
    if rollup is not None and rollup.freshness_state == "LIVE":
        if rollup.trend_30d == "declining":
            why_risk.append("Live usage is declining")
            score -= 8
        else:
            why_ready.append(f"Live usage MAU={rollup.mau}")
            score += 6
    support = customer_support_metrics(db, tenant_id, customer.id)
    if support["open_critical"]:
        why_risk.append(f"{support['open_critical']} critical tickets open")
        score -= 12
    finance = latest_finance(db, tenant_id, customer.id)
    if finance is not None and finance.freshness_state == "LIVE":
        if finance.days_past_due:
            why_risk.append(f"Payment {finance.days_past_due} days past due")
            score -= 12
        elif finance.last_payment_at:
            why_ready.append("Recent payment recorded")
            score += 6
    if open_risks:
        why_risk.append(f"{len(open_risks)} open risks")
        score -= 8 * len(open_risks)
    if customer.arr and customer.arr > 0:
        score += 8
        why_ready.append("Contracted ARR is on the customer record")
    else:
        why_risk.append("ARR unknown")
    readiness = max(0, min(100, score))
    action = "Prepare renewal brief"
    if readiness < 40:
        action = "Engage executive sponsor and recover health"
    elif readiness < 70:
        action = "Close open risks before commercial outreach"
    previous_readiness = renewal.readiness
    renewal.readiness = readiness
    renewal.readiness_version = "rules-v2"
    renewal.risk_factors_json = json.dumps(why_risk)
    renewal.why_ready_json = json.dumps(why_ready)
    renewal.why_at_risk_json = json.dumps(why_risk)
    renewal.confidence = 62 if health else 40
    renewal.recommended_action = action
    from app.services.ml.history import record_entity_field

    record_entity_field(
        db,
        tenant_id=tenant_id,
        actor_id=customer.updated_by,
        entity_type="renewal",
        entity_id=str(renewal.id),
        field_name="readiness",
        old_value=previous_readiness,
        new_value=readiness,
    )
    return {"readiness": readiness, "factors": why_risk, "why_ready": why_ready, "why_at_risk": why_risk, "action": action}


def emit_windows(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, renewal: Renewal, windows: list[int]) -> list[int]:
    if not renewal.renewal_date:
        return []
    remaining = (renewal.renewal_date - date.today()).days
    opened: list[int] = []
    applicable = [day for day in sorted(windows, reverse=True) if remaining <= day]
    if not applicable:
        return []
    window = applicable[-1]
    if renewal.last_window_days == window:
        return []
    key = f"renewal.window:{tenant_id}:{renewal.id}:{window}"
    claimed, _ = claim_key(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        key=key,
        workflow="renewal",
        entity_id=str(renewal.id),
        action_type="renewal.window_opened",
        window=str(window),
    )
    if not claimed:
        renewal.last_window_days = window
        return []
    renewal.last_window_days = window
    renewal.stage = "in_window"
    renewal.status = f"window_{window}"
    set_lifecycle(customer, "RENEWAL_UPCOMING")
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="renewal.window_opened",
        entity_type="renewal",
        entity_id=str(renewal.id),
        payload={"days": window, "customer_id": str(customer.id), "remaining": remaining},
    )
    opened.append(window)
    return opened


def prepare_renewal(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, renewal: Renewal) -> dict:
    contract = None
    if renewal.contract_id or customer.contract_id:
        contract = db.get(Contract, renewal.contract_id or customer.contract_id)
    amount, status = commercial_baseline(contract, renewal)
    renewal.baseline_amount = amount
    renewal.baseline_status = status
    readiness = score_readiness(db, tenant_id=tenant_id, customer=customer, renewal=renewal)
    evidence = {
        "renewal_date": renewal.renewal_date.isoformat() if renewal.renewal_date else None,
        "current_arr": str(renewal.current_arr) if renewal.current_arr else None,
        "baseline_amount": str(amount) if amount is not None else None,
        "baseline_status": status,
        "readiness": readiness,
        "contract_term": contract.term_months if contract else None,
        "escalation_pct": contract.escalation_pct if contract else None,
    }
    source = fingerprint(evidence)
    reused = reuse_or_none(db, tenant_id=tenant_id, kind="renewal_brief", entity_type="renewal", entity_id=str(renewal.id), source_fingerprint=source)
    if reused is None:
        llm = get_llm_provider()
        result = llm.complete(
            json.dumps(evidence, default=str),
            system=(
                "You are RenewalAgent. Prepare a renewal brief from persisted evidence. "
                "Do not invent pricing. If baseline_amount is null, say the commercial number needs review. No tools."
            ),
        )
        reused = upsert_artifact(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            kind="renewal_brief",
            entity_type="renewal",
            entity_id=str(renewal.id),
            title="Renewal brief",
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
    db.add(
        Task(
            tenant_id=tenant_id,
            created_by=actor_id,
            title="Prepare renewal conversation",
            description=renewal.recommended_action,
            status="open",
            priority="high",
            entity_type="renewal",
            entity_id=str(renewal.id),
            source="workflow",
            owner_id=renewal.owner_id or customer.owner_id,
        )
    )
    key = f"renewal.commercial:{renewal.id}:{renewal.last_window_days or 'open'}"
    existing = db.scalar(select(AIApproval).where(AIApproval.tenant_id == tenant_id, AIApproval.idempotency_key == key, AIApproval.deleted_at.is_(None)))
    if existing is None:
        db.add(
            AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="renewal.commercial",
                title="Approve renewal review invitation",
                payload_json=json.dumps(
                    {
                        "customer_id": str(customer.id),
                        "renewal_id": str(renewal.id),
                        "why": f"Renewal window; readiness {renewal.readiness}.",
                        "evidence": json.dumps(evidence, default=str),
                        "risk": "Commercial customer-facing action.",
                        "expected_outcome": "Human-approved renewal outreach.",
                        "body": text[:2000],
                        "subject": "Renewal review",
                        "baseline_amount": str(amount) if amount is not None else None,
                        "baseline_status": status,
                    }
                ),
                status="pending",
                entity_type="renewal",
                entity_id=str(renewal.id),
                idempotency_key=key,
            )
        )
    from app.services.nba import generate_for_renewal

    generate_for_renewal(db, tenant_id, renewal, actor_id)
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="renewal.prepared",
        entity_type="renewal",
        entity_id=str(renewal.id),
        payload={"readiness": renewal.readiness, "baseline_status": status},
    )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="customer",
        entity_id=str(customer.id),
        activity_type="renewal",
        title="Renewal brief prepared",
        body=f"Readiness {renewal.readiness}. Baseline {status}.",
        actor_type="ai",
    )
    return {"readiness": renewal.readiness, "baseline_status": status, "brief": text}


def execute_renewal_commercial(db: Session, *, tenant_id: UUID, actor_id: UUID, approval) -> str:
    payload = {}
    try:
        payload = json.loads(approval.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    renewal_id = payload.get("renewal_id") or approval.entity_id
    renewal = db.get(Renewal, UUID(str(renewal_id)))
    if renewal is None or renewal.tenant_id != tenant_id:
        return "Renewal was not found."
    customer = db.get(Customer, renewal.customer_id)
    if customer:
        set_lifecycle(customer, "RENEWAL_IN_PROGRESS")
    renewal.stage = "commercial_review"
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="renewal.prepared",
        entity_type="renewal",
        entity_id=str(renewal.id),
        payload={"approved": True},
    )
    return "Renewal commercial action recorded. No price was invented."
