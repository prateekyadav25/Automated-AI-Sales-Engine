import json
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Account, Activity, Customer, Lead, Opportunity, Renewal, Task
from app.models.identity import DomainEvent
from app.models.lifecycle import AdvocacyAsset, HealthScore, OnboardingMilestone, OnboardingPlan
from app.models.post_sale import (
    Contract,
    ContractLine,
    CustomerRisk,
    ExpansionRecommendation,
    HandoffPackage,
    ProductUsageSnapshot,
    SuccessPlanObjective,
)
from app.schemas.crm import CustomerOut
from app.schemas.post_sale import (
    ContractLineOut,
    ContractOut,
    Customer360Out,
    CustomerRiskOut,
    ExpansionRecOut,
    HandoffOut,
    SuccessObjectiveOut,
    TimelineItemOut,
    TimeToValueOut,
    UsageSnapshotOut,
)
from app.services.autopilot_status import entity_trace
from app.services.expansion import growth_plan
from app.services.onboarding import time_to_value


def build_customer_360(db: Session, *, tenant_id: UUID, customer: Customer) -> Customer360Out:
    account = db.scalar(select(Account).where(Account.id == customer.account_id, Account.tenant_id == tenant_id))
    payload = CustomerOut.model_validate(customer)
    payload.account_name = account.name if account else None
    health = db.scalar(select(HealthScore).where(HealthScore.tenant_id == tenant_id, HealthScore.customer_id == customer.id, HealthScore.deleted_at.is_(None)))
    renewal = db.scalar(select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None)))
    countdown = None
    if renewal and renewal.renewal_date:
        countdown = (renewal.renewal_date - date.today()).days
    contract_row = db.scalar(select(Contract).where(Contract.tenant_id == tenant_id, Contract.customer_id == customer.id, Contract.deleted_at.is_(None)))
    contract = None
    if contract_row:
        lines = db.scalars(select(ContractLine).where(ContractLine.contract_id == contract_row.id)).all()
        contract = ContractOut.model_validate(contract_row).model_copy(
            update={"lines": [ContractLineOut.model_validate(line) for line in lines]}
        )
    handoff_row = db.scalar(select(HandoffPackage).where(HandoffPackage.tenant_id == tenant_id, HandoffPackage.customer_id == customer.id))
    handoff = None
    if handoff_row:
        try:
            body = json.loads(handoff_row.payload_json or "{}")
            missing = json.loads(handoff_row.missing_fields_json or "[]")
            risks = json.loads(handoff_row.risks_json or "[]")
        except json.JSONDecodeError:
            body, missing, risks = {}, [], []
        handoff = HandoffOut(
            id=handoff_row.id,
            customer_id=customer.id,
            status=handoff_row.status,
            payload=body if isinstance(body, dict) else {},
            missing_fields=missing if isinstance(missing, list) else [],
            risks=risks if isinstance(risks, list) else [],
            kickoff_agenda=handoff_row.kickoff_agenda,
        )
    plan = db.scalar(select(OnboardingPlan).where(OnboardingPlan.tenant_id == tenant_id, OnboardingPlan.customer_id == customer.id))
    milestones = []
    if plan:
        milestones = [
            {"id": str(row.id), "title": row.title, "status": row.status, "due_date": row.due_date.isoformat() if row.due_date else None}
            for row in db.scalars(select(OnboardingMilestone).where(OnboardingMilestone.plan_id == plan.id).order_by(OnboardingMilestone.position.asc())).all()
        ]
    usage_row = db.scalar(
        select(ProductUsageSnapshot)
        .where(ProductUsageSnapshot.tenant_id == tenant_id, ProductUsageSnapshot.customer_id == customer.id)
        .order_by(ProductUsageSnapshot.created_at.desc())
    )
    risks = [
        CustomerRiskOut(
            id=row.id,
            customer_id=row.customer_id,
            risk_type=row.risk_type,
            severity=row.severity,
            summary=row.summary,
            evidence=json.loads(row.evidence_json or "{}") if str(row.evidence_json or "").startswith("{") else {},
            status=row.status,
            detected_at=row.detected_at,
            resolved_at=row.resolved_at,
        )
        for row in db.scalars(select(CustomerRisk).where(CustomerRisk.tenant_id == tenant_id, CustomerRisk.customer_id == customer.id)).all()
    ]
    expansion = [
        ExpansionRecOut.model_validate(row)
        for row in db.scalars(
            select(ExpansionRecommendation).where(ExpansionRecommendation.tenant_id == tenant_id, ExpansionRecommendation.customer_id == customer.id)
        ).all()
    ]
    advocacy = [
        {"id": str(row.id), "type": row.advocacy_type or row.kind, "status": row.status, "score": row.eligibility_score, "quote": row.quote}
        for row in db.scalars(select(AdvocacyAsset).where(AdvocacyAsset.tenant_id == tenant_id, AdvocacyAsset.customer_id == customer.id)).all()
    ]
    objectives = [
        SuccessObjectiveOut.model_validate(row)
        for row in db.scalars(select(SuccessPlanObjective).where(SuccessPlanObjective.tenant_id == tenant_id, SuccessPlanObjective.customer_id == customer.id)).all()
    ]
    automation = entity_trace(db, tenant_id=tenant_id, entity_type="customer", entity_id=str(customer.id))
    timeline = _timeline(db, tenant_id, customer)
    ttv = time_to_value(customer)
    from app.services.finance_ingest import latest_finance
    from app.services.support_ingest import customer_support_metrics, latest_support
    from app.services.usage_ingest import latest_rollup

    rollup = latest_rollup(db, tenant_id, customer.id)
    support_row = latest_support(db, tenant_id, customer.id)
    finance_row = latest_finance(db, tenant_id, customer.id)
    usage_freshness = "MOCK"
    if rollup is not None and not rollup.is_mock:
        usage_freshness = rollup.freshness_state
    elif usage_row and usage_row.is_mock:
        usage_freshness = "MOCK"
    support_freshness = "NOT_CONNECTED"
    if support_row is not None:
        support_freshness = support_row.freshness_state
    finance_freshness = "NOT_CONNECTED"
    if finance_row is not None:
        finance_freshness = finance_row.freshness_state
    components = {}
    if health and health.components_json:
        try:
            components = json.loads(health.components_json)
        except json.JSONDecodeError:
            components = {}
    why_ready: list[str] = []
    why_risk: list[str] = []
    if renewal:
        try:
            why_ready = json.loads(renewal.why_ready_json or "[]")
            why_risk = json.loads(renewal.why_at_risk_json or "[]")
        except json.JSONDecodeError:
            why_ready, why_risk = [], []
    metrics = customer_support_metrics(db, tenant_id, customer.id)
    return Customer360Out(
        customer=payload,
        account_name=account.name if account else "",
        lifecycle_state=customer.lifecycle_state,
        health_total=health.total if health else None,
        health_trend=customer.health_trend,
        health_version=health.version if health else "rules-v2",
        health_data_coverage=health.health_data_coverage if health else 0,
        health_components=components if isinstance(components, dict) else {},
        unavailable_components=health.unavailable_components if health else "",
        usage_freshness=usage_freshness,
        support_freshness=support_freshness,
        finance_freshness=finance_freshness,
        commercial_freshness="LIVE",
        last_usage_at=rollup.last_activity_at if rollup else (usage_row.last_activity_at if usage_row else None),
        last_support_at=support_row.last_event_at if support_row else None,
        last_finance_at=finance_row.last_event_at if finance_row else None,
        support_open_critical=metrics["open_critical"],
        finance_outstanding=str(finance_row.outstanding_balance) if finance_row and finance_row.outstanding_balance is not None else None,
        renewal_why_ready=why_ready if isinstance(why_ready, list) else [],
        renewal_why_at_risk=why_risk if isinstance(why_risk, list) else [],
        risks=risks,
        renewal_date=renewal.renewal_date if renewal else None,
        renewal_readiness=renewal.readiness if renewal else 0,
        renewal_countdown_days=countdown,
        contract=contract,
        handoff=handoff,
        onboarding_status=plan.status if plan else "",
        milestones=milestones,
        usage=UsageSnapshotOut.model_validate(usage_row) if usage_row else None,
        expansion=expansion,
        advocacy=advocacy,
        objectives=objectives,
        automation=automation.model_dump(),
        timeline=timeline,
        time_to_value=TimeToValueOut(**ttv),
        growth_plan=growth_plan(db, tenant_id=tenant_id, customer=customer),
    )


def _timeline(db: Session, tenant_id: UUID, customer: Customer) -> list[TimelineItemOut]:
    rows: list[TimelineItemOut] = []
    events = db.scalars(
        select(DomainEvent)
        .where(DomainEvent.tenant_id == tenant_id, DomainEvent.entity_id.in_([str(customer.id), str(customer.account_id), str(customer.opportunity_id or "")]))
        .order_by(DomainEvent.created_at.asc())
        .limit(80)
    ).all()
    skip = {"user.active", "user.login", "api.requested", "feature.used"}
    for event in events:
        if event.event_type in skip:
            continue
        rows.append(
            TimelineItemOut(
                occurred_at=event.created_at,
                kind="event",
                title=event.event_type,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                source="domain_events",
            )
        )
    activities = db.scalars(
        select(Activity)
        .where(
            Activity.tenant_id == tenant_id,
            Activity.entity_id.in_([str(customer.id), str(customer.account_id), str(customer.opportunity_id or "")]),
            Activity.deleted_at.is_(None),
        )
        .order_by(Activity.created_at.asc())
        .limit(40)
    ).all()
    for activity in activities:
        rows.append(
            TimelineItemOut(
                occurred_at=activity.created_at,
                kind="activity",
                title=activity.title,
                entity_type=activity.entity_type,
                entity_id=activity.entity_id,
                source=activity.activity_type,
            )
        )
    if customer.opportunity_id:
        opp = db.get(Opportunity, customer.opportunity_id)
        if opp:
            rows.append(
                TimelineItemOut(
                    occurred_at=opp.created_at,
                    kind="opportunity",
                    title=opp.name,
                    entity_type="opportunity",
                    entity_id=str(opp.id),
                    source=opp.stage,
                )
            )
    leads = db.scalars(select(Lead).where(Lead.tenant_id == tenant_id, Lead.account_id == customer.account_id, Lead.deleted_at.is_(None)).limit(5)).all()
    for lead in leads:
        rows.append(
            TimelineItemOut(
                occurred_at=lead.created_at,
                kind="lead",
                title=f"{lead.first_name} {lead.last_name}",
                entity_type="lead",
                entity_id=str(lead.id),
                source=lead.source,
            )
        )
    _ = Task
    rows.sort(key=lambda row: row.occurred_at)
    return rows
