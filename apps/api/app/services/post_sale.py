from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Account, Customer, Opportunity, Renewal, Task
from app.models.lifecycle import Quote, QuoteLine, SuccessPlan
from app.models.post_sale import Contract, ContractLine
from app.services.advocacy import evaluate_advocacy, ingest_referral
from app.services.audit import emit_event
from app.services.automation_state import is_entity_paused, upsert_state
from app.services.autopilot_settings import get_or_create_settings
from app.services.crm import add_activity
from app.services.customer_health import recalculate
from app.services.customer_lifecycle import mark_activated, select_cs_owner, select_customer_owner, set_lifecycle
from app.services.customer_risk import detect_risks, run_success_agent
from app.services.expansion import detect_expansion
from app.services.handoff import ensure_handoff
from app.services.idempotency import claim_key
from app.services.nba import generate_for_customer
from app.services.onboarding import start_onboarding
from app.services.qbr import prepare_qbr
from app.services.renewal import emit_windows, parse_windows, prepare_renewal


def mint_contract(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, account: Account, opportunity: Opportunity) -> Contract:
    existing = db.scalar(
        select(Contract).where(
            Contract.tenant_id == tenant_id,
            Contract.customer_id == customer.id,
            Contract.deleted_at.is_(None),
        )
    )
    if existing is not None:
        customer.contract_id = existing.id
        return existing
    quote = db.scalar(
        select(Quote)
        .where(Quote.tenant_id == tenant_id, Quote.opportunity_id == opportunity.id, Quote.deleted_at.is_(None))
        .order_by(Quote.created_at.desc())
    )
    total = quote.total if quote and quote.total else (opportunity.amount or None)
    if total == 0:
        total = None
    start = date.today()
    contract = Contract(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer.id,
        account_id=account.id,
        opportunity_id=opportunity.id,
        quote_id=quote.id if quote else None,
        status="active",
        source="closed_won",
        start_date=start,
        end_date=start + timedelta(days=365),
        term_months=None,
        total_value=total,
        escalation_pct=None,
    )
    db.add(contract)
    db.flush()
    if quote:
        for line in db.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id, QuoteLine.deleted_at.is_(None))).all():
            db.add(
                ContractLine(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    contract_id=contract.id,
                    product_id=line.product_id,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    line_total=line.line_total,
                )
            )
    customer.contract_id = contract.id
    return contract


def ensure_renewal(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, account: Account, contract: Contract | None) -> Renewal:
    existing = db.scalar(
        select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None))
    )
    if existing is not None:
        if contract:
            existing.contract_id = contract.id
            existing.current_arr = contract.total_value or existing.current_arr
        return existing
    end = contract.end_date if contract and contract.end_date else (date.today() + timedelta(days=365))
    renewal = Renewal(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer.id,
        account_id=account.id,
        renewal_date=end,
        current_arr=contract.total_value if contract and contract.total_value is not None else (customer.arr or Decimal("0")),
        status="monitoring",
        owner_id=customer.owner_id,
        contract_id=contract.id if contract else None,
        term_months=contract.term_months if contract else None,
        stage="monitoring",
        baseline_status="needs_review",
    )
    db.add(renewal)
    db.flush()
    return renewal


def ensure_success_plan(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, account_name: str) -> SuccessPlan:
    existing = db.scalar(
        select(SuccessPlan).where(SuccessPlan.tenant_id == tenant_id, SuccessPlan.customer_id == customer.id, SuccessPlan.deleted_at.is_(None))
    )
    if existing is not None:
        return existing
    row = SuccessPlan(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer.id,
        objective=f"Governed outcomes for {account_name}. Metrics stay proposed until validated.",
        status="active",
    )
    db.add(row)
    db.flush()
    emit_event(db, tenant_id=tenant_id, event_type="success_plan.updated", entity_type="customer", entity_id=str(customer.id))
    return row


def activate_customer(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    customer: Customer,
    account: Account,
    opportunity: Opportunity,
    correlation_id: str = "",
) -> dict:
    key = f"customer.activation:{tenant_id}:{opportunity.id}"
    claimed, _ = claim_key(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        key=key,
        workflow="customer_activation",
        entity_id=str(customer.id),
        action_type="customer.activate",
    )
    if not claimed:
        renewal = ensure_renewal(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, account=account, contract=None)
        return {"reused": True, "customer_id": str(customer.id), "renewal_id": str(renewal.id)}
    owner = select_customer_owner(db, tenant_id=tenant_id, opportunity=opportunity, account=account)
    csm = select_cs_owner(db, tenant_id=tenant_id, account=account)
    customer.owner_id = customer.owner_id or (owner.id if owner else None)
    customer.csm_owner_id = customer.csm_owner_id or (csm.id if csm else None)
    set_lifecycle(customer, "NEW_CUSTOMER")
    mark_activated(customer)
    contract = mint_contract(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, account=account, opportunity=opportunity)
    renewal = ensure_renewal(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, account=account, contract=contract)
    handoff = ensure_handoff(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, account=account, opportunity=opportunity)
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    start_onboarding(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, account=account, auto_tasks=settings.auto_create_internal_tasks)
    ensure_success_plan(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, account_name=account.name)
    if settings.customer_health_enabled or settings.customer_success_enabled:
        recalculate(db, tenant_id, customer, actor_id)
    generate_for_customer(db, tenant_id, customer, actor_id)
    existing_task = db.scalar(
        select(Task).where(
            Task.tenant_id == tenant_id,
            Task.entity_type == "customer",
            Task.entity_id == str(customer.id),
            Task.title.startswith("Sales-to-success handoff"),
            Task.deleted_at.is_(None),
        )
    )
    if existing_task is None:
        db.add(
            Task(
                tenant_id=tenant_id,
                created_by=actor_id,
                title=f"Sales-to-success handoff: {account.name}",
                description="Review the persisted handoff package and run kickoff.",
                status="open",
                priority="high",
                entity_type="customer",
                entity_id=str(customer.id),
                source="workflow",
                owner_id=customer.csm_owner_id or actor_id,
            )
        )
    upsert_state(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="customer",
        entity_id=str(customer.id),
        state="ONBOARDING",
        last_action="customer_activated",
        next_action="complete_kickoff",
        blocked_reason="" if customer.csm_owner_id or customer.owner_id else "BLOCKED BY CONFIGURATION",
    )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="customer",
        entity_id=str(customer.id),
        activity_type="activation",
        title="Customer created",
        body="Activation, handoff, onboarding, and renewal are persisted.",
        actor_type="ai",
    )
    _ = correlation_id, datetime, UTC, handoff
    return {"reused": False, "customer_id": str(customer.id), "renewal_id": str(renewal.id), "contract_id": str(contract.id)}


POST_SALE_EVENTS = {
    "customer.created",
    "handoff.created",
    "onboarding.started",
    "onboarding.milestone_due",
    "onboarding.completed",
    "customer.health_changed",
    "customer.risk_detected",
    "customer.risk_resolved",
    "success_plan.updated",
    "qbr.upcoming",
    "qbr.prepared",
    "qbr.completed",
    "renewal.window_opened",
    "renewal.risk_changed",
    "renewal.prepared",
    "renewal.completed",
    "upsell.detected",
    "cross_sell.detected",
    "expansion.detected",
    "advocacy.eligible",
    "advocacy.approved",
    "referral.received",
    "deal.won",
    "mapping.confirmed",
    "commercial.mismatch",
}


def _customer(db: Session, tenant_id: UUID, entity_type: str, entity_id: str) -> Customer | None:
    if entity_type == "customer":
        return db.scalar(select(Customer).where(Customer.tenant_id == tenant_id, Customer.id == UUID(entity_id), Customer.deleted_at.is_(None)))
    if entity_type == "renewal":
        renewal = db.scalar(select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.id == UUID(entity_id)))
        if renewal:
            return db.get(Customer, renewal.customer_id)
    return None


def handle_post_sale_event(db: Session, event, *, actor_id: UUID | None = None) -> str:
    if event.event_type not in POST_SALE_EVENTS:
        return "ignored"
    tenant_id = event.tenant_id
    actor = actor_id or event.tenant_id
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    if event.event_type == "deal.won":
        payload = {}
        try:
            import json

            payload = json.loads(event.payload_json or "{}")
        except Exception:
            payload = {}
        customer_id = payload.get("customer_id") or event.entity_id
        customer = db.scalar(select(Customer).where(Customer.tenant_id == tenant_id, Customer.id == UUID(str(customer_id)), Customer.deleted_at.is_(None)))
        if customer is None:
            return "missing_customer"
        account = db.get(Account, customer.account_id)
        opportunity = db.get(Opportunity, UUID(event.entity_id)) if event.entity_type == "opportunity" else None
        if account and opportunity:
            activate_customer(db, tenant_id=tenant_id, actor_id=actor, customer=customer, account=account, opportunity=opportunity)
            from app.services.ml_labels import record_outcome

            record_outcome(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                entity_type="opportunity",
                entity_id=str(opportunity.id),
                outcome_type="OPPORTUNITY_WON",
                evidence={"customer_id": str(customer.id)},
                occurred_at=opportunity.updated_at,
            )
            from app.services.ml.history import record_opportunity_fields

            record_opportunity_fields(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                opportunity_id=opportunity.id,
                changes={"stage": (opportunity.stage if opportunity.stage != "closed_won" else "commit", "closed_won")},
            )
        return "activated"
    customer = _customer(db, tenant_id, event.entity_type, event.entity_id)
    if customer is None and event.event_type == "customer.created":
        customer = db.scalar(select(Customer).where(Customer.tenant_id == tenant_id, Customer.id == UUID(event.entity_id), Customer.deleted_at.is_(None)))
    if customer is None:
        if event.event_type == "referral.received":
            return "referral"
        return "missing_customer"
    if is_entity_paused(db, tenant_id=tenant_id, entity_type="customer", entity_id=str(customer.id)):
        return "paused"
    if event.event_type == "customer.created":
        account = db.get(Account, customer.account_id)
        opportunity = db.get(Opportunity, customer.opportunity_id) if customer.opportunity_id else None
        if account and opportunity:
            activate_customer(db, tenant_id=tenant_id, actor_id=actor, customer=customer, account=account, opportunity=opportunity)
        return "activated"
    if event.event_type == "onboarding.milestone_due":
        detect_risks(db, tenant_id=tenant_id, actor_id=actor, customer=customer)
        generate_for_customer(db, tenant_id, customer, actor)
        return "onboarding_due"
    if event.event_type == "customer.health_changed" and settings.customer_health_enabled:
        risks = detect_risks(db, tenant_id=tenant_id, actor_id=actor, customer=customer)
        if risks:
            run_success_agent(db, tenant_id=tenant_id, actor_id=actor, customer=customer, risk=risks[0])
        return "health"
    if event.event_type == "customer.risk_detected" and settings.customer_success_enabled:
        from app.models.post_sale import CustomerRisk

        risk = db.scalar(
            select(CustomerRisk).where(CustomerRisk.tenant_id == tenant_id, CustomerRisk.customer_id == customer.id, CustomerRisk.status == "open")
        )
        if risk:
            run_success_agent(db, tenant_id=tenant_id, actor_id=actor, customer=customer, risk=risk)
        return "risk"
    if event.event_type == "renewal.window_opened" and settings.renewal_enabled:
        renewal = db.scalar(select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None)))
        if renewal:
            prepare_renewal(db, tenant_id=tenant_id, actor_id=actor, customer=customer, renewal=renewal)
        return "renewal"
    if event.event_type == "qbr.upcoming" and settings.qbr_automation_enabled:
        prepare_qbr(db, tenant_id=tenant_id, actor_id=actor, customer=customer)
        return "qbr"
    if event.event_type in {"upsell.detected", "cross_sell.detected", "expansion.detected"}:
        return "expansion_recorded"
    if event.event_type == "advocacy.eligible" and settings.advocacy_enabled:
        return "advocacy_recorded"
    if event.event_type == "referral.received":
        return "referral"
    _ = emit_windows, parse_windows, detect_expansion, evaluate_advocacy, ingest_referral
    return "recorded"
