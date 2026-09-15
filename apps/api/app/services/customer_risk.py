import json
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.models.ai import AIApproval
from app.models.crm import Customer, Renewal, Task
from app.models.lifecycle import HealthScore, OnboardingMilestone, OnboardingPlan
from app.models.post_sale import CustomerRisk
from app.services.ai_artifacts import fingerprint, reuse_or_none, upsert_artifact
from app.services.audit import emit_event
from app.services.automation_state import upsert_state
from app.services.crm import add_activity
from app.services.customer_lifecycle import set_lifecycle


def _open_risk(db: Session, tenant_id: UUID, customer_id: UUID, risk_type: str) -> CustomerRisk | None:
    return db.scalar(
        select(CustomerRisk).where(
            CustomerRisk.tenant_id == tenant_id,
            CustomerRisk.customer_id == customer_id,
            CustomerRisk.risk_type == risk_type,
            CustomerRisk.status == "open",
            CustomerRisk.deleted_at.is_(None),
        )
    )


def _raise_risk(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    customer: Customer,
    risk_type: str,
    severity: str,
    summary: str,
    evidence: dict,
) -> CustomerRisk:
    existing = _open_risk(db, tenant_id, customer.id, risk_type)
    if existing is not None:
        existing.evidence_json = json.dumps(evidence, default=str)
        existing.summary = summary
        existing.severity = severity
        return existing
    row = CustomerRisk(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer.id,
        account_id=customer.account_id,
        risk_type=risk_type,
        severity=severity,
        evidence_json=json.dumps(evidence, default=str),
        summary=summary,
        ruleset_version="risk-v2",
        status="open",
        detected_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="customer.risk_detected",
        entity_type="customer",
        entity_id=str(customer.id),
        payload={"risk_id": str(row.id), "risk_type": risk_type, "severity": severity},
    )
    return row


def detect_risks(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer) -> list[CustomerRisk]:
    raised: list[CustomerRisk] = []
    plan = db.scalar(
        select(OnboardingPlan).where(OnboardingPlan.tenant_id == tenant_id, OnboardingPlan.customer_id == customer.id, OnboardingPlan.deleted_at.is_(None))
    )
    if plan:
        overdue = db.scalars(
            select(OnboardingMilestone).where(
                OnboardingMilestone.plan_id == plan.id,
                OnboardingMilestone.deleted_at.is_(None),
                OnboardingMilestone.status.notin_(["done", "completed"]),
                OnboardingMilestone.due_date.is_not(None),
                OnboardingMilestone.due_date < date.today(),
            )
        ).all()
        if overdue:
            raised.append(
                _raise_risk(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    customer=customer,
                    risk_type="onboarding_delay",
                    severity="high",
                    summary=f"{len(overdue)} onboarding milestone(s) overdue.",
                    evidence={"titles": [row.title for row in overdue]},
                )
            )
    health = db.scalar(
        select(HealthScore).where(HealthScore.tenant_id == tenant_id, HealthScore.customer_id == customer.id, HealthScore.deleted_at.is_(None))
    )
    if health and health.trend == "declining":
        raised.append(
            _raise_risk(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                customer=customer,
                risk_type="USAGE_DECLINE",
                severity="medium",
                summary=f"Health trend is declining (score {health.total}).",
                evidence={"total": health.total, "trend": health.trend, "version": health.version},
            )
        )
    from app.services.autopilot_settings import get_or_create_settings
    from app.services.finance_ingest import latest_finance
    from app.services.support_ingest import customer_support_metrics
    from app.services.usage_ingest import latest_rollup

    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    rollup = latest_rollup(db, tenant_id, customer.id)
    if rollup is not None and rollup.freshness_state == "LIVE" and not rollup.is_mock:
        if rollup.trend_30d == "declining":
            raised.append(
                _raise_risk(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    customer=customer,
                    risk_type="USAGE_DECLINE",
                    severity="high",
                    summary="Live usage rollup is declining over 30 days.",
                    evidence={"trend_30d": rollup.trend_30d, "dau": rollup.dau, "mau": rollup.mau},
                )
            )
        if rollup.utilization_pct is not None and rollup.utilization_pct < settings.low_utilization_pct:
            raised.append(
                _raise_risk(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    customer=customer,
                    risk_type="ADOPTION_RISK",
                    severity="medium",
                    summary=f"Utilization {rollup.utilization_pct}% is below the low-adoption threshold.",
                    evidence={"utilization_pct": rollup.utilization_pct, "seats_active": rollup.seats_active, "seats_licensed": rollup.seats_licensed},
                )
            )
    metrics = customer_support_metrics(db, tenant_id, customer.id)
    if metrics["open_critical"]:
        raised.append(
            _raise_risk(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                customer=customer,
                risk_type="SUPPORT_RISK",
                severity="high",
                summary=f"{metrics['open_critical']} critical support ticket(s) are open.",
                evidence=metrics,
            )
        )
    finance = latest_finance(db, tenant_id, customer.id)
    if finance is not None and finance.freshness_state == "LIVE" and ((finance.days_past_due or 0) > 0 or finance.credit_hold):
        raised.append(
            _raise_risk(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                customer=customer,
                risk_type="COMMERCIAL_RISK",
                severity="high",
                summary="Payment is overdue or credit is on hold.",
                evidence={"days_past_due": finance.days_past_due, "credit_hold": finance.credit_hold, "status": finance.status},
            )
        )
    last = db.scalar(
        select(Customer).where(Customer.id == customer.id)
    )
    _ = last
    from app.models.crm import Activity

    latest = db.scalar(
        select(Activity)
        .where(
            Activity.tenant_id == tenant_id,
            Activity.entity_type.in_(["customer", "account"]),
            Activity.entity_id.in_([str(customer.id), str(customer.account_id)]),
            Activity.deleted_at.is_(None),
        )
        .order_by(Activity.created_at.desc())
    )
    if latest is None or (datetime.now(UTC) - (latest.created_at if latest.created_at.tzinfo else latest.created_at.replace(tzinfo=UTC))).days >= 21:
        raised.append(
            _raise_risk(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                customer=customer,
                risk_type="no_recent_engagement",
                severity="medium",
                summary="No customer activity in 21 days.",
                evidence={"last_activity": latest.created_at.isoformat() if latest else None},
            )
        )
    renewal = db.scalar(
        select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None))
    )
    if renewal and renewal.renewal_date and health and health.total < 50:
        days = (renewal.renewal_date - date.today()).days
        if 0 <= days <= 90:
            raised.append(
                _raise_risk(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    customer=customer,
                    risk_type="RENEWAL_RISK",
                    severity="high",
                    summary=f"Renewal in {days} days with health {health.total}.",
                    evidence={"days": days, "health": health.total},
                )
            )
    if raised:
        set_lifecycle(customer, "AT_RISK")
    return raised


def run_success_agent(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, risk: CustomerRisk) -> dict:
    source = fingerprint({"risk": risk.risk_type, "evidence": risk.evidence_json, "health": customer.health_trend})
    reused = reuse_or_none(db, tenant_id=tenant_id, kind="cs_intervention", entity_type="customer", entity_id=str(customer.id), source_fingerprint=source)
    if reused is None:
        llm = get_llm_provider()
        result = llm.complete(
            json.dumps({"risk": risk.risk_type, "summary": risk.summary, "evidence": risk.evidence_json}, default=str),
            system=(
                "You are CustomerSuccessAgent. Prepare a risk summary, likely cause, evidence recap, "
                "recommended intervention, and a suggested customer communication. "
                "Do not change contracts, prices, or promise product capability. No tools. Do not send."
            ),
        )
        content = {"brief": result.text, "risk_type": risk.risk_type}
        reused = upsert_artifact(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            kind="cs_intervention",
            entity_type="customer",
            entity_id=str(customer.id),
            title=f"CS intervention: {risk.risk_type}",
            content=content,
            source_fingerprint=source,
            provider=result.provider,
            is_mock=result.is_mock,
        )
        text = result.text
        provider = result.provider
        is_mock = result.is_mock
    else:
        try:
            text = json.loads(reused.content_json).get("brief") or reused.content_json
        except json.JSONDecodeError:
            text = reused.content_json
        provider = reused.provider
        is_mock = reused.is_mock
    db.add(
        Task(
            tenant_id=tenant_id,
            created_by=actor_id,
            title=f"Resolve {risk.risk_type.replace('_', ' ')}",
            description=risk.summary,
            status="open",
            priority="high" if risk.severity == "high" else "medium",
            entity_type="customer",
            entity_id=str(customer.id),
            source="workflow",
            owner_id=customer.csm_owner_id,
        )
    )
    key = f"customer.risk.email:{customer.id}:{risk.risk_type}"
    existing = db.scalar(select(AIApproval).where(AIApproval.tenant_id == tenant_id, AIApproval.idempotency_key == key, AIApproval.deleted_at.is_(None)))
    if existing is None:
        db.add(
            AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="customer.success.send",
                title=f"Send CS intervention note for {risk.risk_type.replace('_', ' ')}",
                payload_json=json.dumps(
                    {
                        "customer_id": str(customer.id),
                        "lead_id": "",
                        "why": risk.summary,
                        "evidence": risk.evidence_json,
                        "risk": risk.severity,
                        "expected_outcome": "Human-approved customer communication.",
                        "body": text[:2000],
                        "subject": "Checking in on your rollout",
                    }
                ),
                status="pending",
                entity_type="customer",
                entity_id=str(customer.id),
                idempotency_key=key,
            )
        )
    upsert_state(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="customer",
        entity_id=str(customer.id),
        state="AT_RISK",
        last_action="risk_intervention_prepared",
        next_action="approve_cs_communication",
        blocked_reason="",
    )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="customer",
        entity_id=str(customer.id),
        activity_type="risk",
        title=f"Risk detected: {risk.risk_type.replace('_', ' ')}",
        body=risk.summary,
        actor_type="ai",
    )
    return {"brief": text, "provider": provider, "is_mock": is_mock}
