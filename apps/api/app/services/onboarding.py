from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Account, Customer, Task
from app.models.lifecycle import OnboardingMilestone, OnboardingPlan, Product, Quote, QuoteLine
from app.models.post_sale import OnboardingTemplate, OnboardingTemplateItem
from app.services.audit import emit_event
from app.services.automation_state import upsert_state
from app.services.crm import add_activity
from app.services.customer_lifecycle import select_cs_owner, select_customer_owner, set_lifecycle

DEFAULT_ITEMS = [
    ("Kickoff", "KICKOFF_PENDING", 3, 5, "csm", "kickoff_notes"),
    ("Technical setup", "IMPLEMENTATION", 7, 10, "implementation", "environment_ready"),
    ("Integration", "IMPLEMENTATION", 14, 14, "implementation", "integration_complete"),
    ("Data preparation", "IMPLEMENTATION", 18, 10, "implementation", "data_loaded"),
    ("Training", "TRAINING", 24, 7, "csm", "training_complete"),
    ("User enablement", "ADOPTION", 30, 10, "csm", "users_enabled"),
    ("Acceptance", "ACCEPTANCE", 40, 7, "csm", "acceptance_signoff"),
    ("Go-live", "LIVE", 45, 5, "csm", "go_live"),
]


def ensure_default_template(db: Session, *, tenant_id: UUID, actor_id: UUID) -> OnboardingTemplate:
    row = db.scalar(
        select(OnboardingTemplate).where(
            OnboardingTemplate.tenant_id == tenant_id,
            OnboardingTemplate.key == "default",
            OnboardingTemplate.deleted_at.is_(None),
        )
    )
    if row is not None:
        return row
    row = OnboardingTemplate(
        tenant_id=tenant_id,
        created_by=actor_id,
        key="default",
        name="Standard onboarding",
        is_default=True,
        objective="Land first value without inventing commitments.",
    )
    db.add(row)
    db.flush()
    for position, (title, stage, offset, sla, role, evidence) in enumerate(DEFAULT_ITEMS, start=1):
        db.add(
            OnboardingTemplateItem(
                tenant_id=tenant_id,
                created_by=actor_id,
                template_id=row.id,
                title=title,
                stage=stage,
                position=position,
                offset_days=offset,
                sla_days=sla,
                owner_role=role,
                depends_on_position=position - 1 if position > 1 else None,
                required_evidence=evidence,
                task_title=title,
            )
        )
    db.flush()
    return row


def select_template(db: Session, *, tenant_id: UUID, actor_id: UUID, account: Account, product_sku: str = "") -> OnboardingTemplate:
    if product_sku:
        match = db.scalar(
            select(OnboardingTemplate).where(
                OnboardingTemplate.tenant_id == tenant_id,
                OnboardingTemplate.product_sku == product_sku,
                OnboardingTemplate.deleted_at.is_(None),
            )
        )
        if match is not None:
            return match
    if account.industry:
        match = db.scalar(
            select(OnboardingTemplate).where(
                OnboardingTemplate.tenant_id == tenant_id,
                OnboardingTemplate.industry == account.industry,
                OnboardingTemplate.deleted_at.is_(None),
            )
        )
        if match is not None:
            return match
    return ensure_default_template(db, tenant_id=tenant_id, actor_id=actor_id)


def _resolve_owner(db: Session, *, tenant_id: UUID, customer: Customer, account: Account, role: str):
    if role == "implementation":
        return select_cs_owner(db, tenant_id=tenant_id, account=account)
    if role == "csm":
        if customer.csm_owner_id:
            from app.models.identity import User

            user = db.scalar(select(User).where(User.id == customer.csm_owner_id, User.tenant_id == tenant_id, User.is_active.is_(True)))
            if user is not None:
                return user
        return select_cs_owner(db, tenant_id=tenant_id, account=account)
    opportunity = None
    if customer.opportunity_id:
        from app.models.crm import Opportunity

        opportunity = db.get(Opportunity, customer.opportunity_id)
    return select_customer_owner(db, tenant_id=tenant_id, opportunity=opportunity, account=account)


def start_onboarding(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    customer: Customer,
    account: Account,
    auto_tasks: bool = True,
) -> OnboardingPlan:
    plan = db.scalar(
        select(OnboardingPlan).where(
            OnboardingPlan.tenant_id == tenant_id,
            OnboardingPlan.customer_id == customer.id,
            OnboardingPlan.deleted_at.is_(None),
        )
    )
    if plan is not None:
        existing = db.scalars(select(OnboardingMilestone).where(OnboardingMilestone.plan_id == plan.id, OnboardingMilestone.deleted_at.is_(None))).all()
        if existing:
            return plan
    sku = ""
    if customer.opportunity_id:
        quote = db.scalar(
            select(Quote).where(Quote.tenant_id == tenant_id, Quote.opportunity_id == customer.opportunity_id, Quote.deleted_at.is_(None))
        )
        if quote:
            line = db.scalar(select(QuoteLine).where(QuoteLine.quote_id == quote.id, QuoteLine.deleted_at.is_(None)))
            if line:
                product = db.get(Product, line.product_id)
                sku = product.sku if product else ""
    template = select_template(db, tenant_id=tenant_id, actor_id=actor_id, account=account, product_sku=sku)
    items = db.scalars(
        select(OnboardingTemplateItem)
        .where(OnboardingTemplateItem.template_id == template.id, OnboardingTemplateItem.deleted_at.is_(None))
        .order_by(OnboardingTemplateItem.position.asc())
    ).all()
    if plan is None:
        plan = OnboardingPlan(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=customer.id,
            status="ONBOARDING_STARTED",
            objective=template.objective or f"Land value for {account.name}.",
        )
        db.add(plan)
        db.flush()
    else:
        plan.status = "ONBOARDING_STARTED"
    created: list[OnboardingMilestone] = []
    missing_owner = False
    for item in items:
        owner = _resolve_owner(db, tenant_id=tenant_id, customer=customer, account=account, role=item.owner_role)
        if owner is None:
            missing_owner = True
        milestone = OnboardingMilestone(
            tenant_id=tenant_id,
            created_by=actor_id,
            plan_id=plan.id,
            title=item.title,
            due_date=date.today() + timedelta(days=item.offset_days),
            status="blocked" if owner is None else "open",
            owner_id=owner.id if owner else None,
            position=item.position,
            sla_days=item.sla_days,
            required_evidence=item.required_evidence,
            template_key=template.key,
        )
        db.add(milestone)
        created.append(milestone)
        if auto_tasks:
            db.add(
                Task(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    title=item.task_title or item.title,
                    description=f"Onboarding milestone. Evidence: {item.required_evidence or 'none specified'}.",
                    status="open",
                    priority="high" if item.position <= 2 else "medium",
                    due_at=datetime.combine(milestone.due_date, datetime.min.time(), tzinfo=UTC) if milestone.due_date else None,
                    owner_id=owner.id if owner else None,
                    entity_type="customer",
                    entity_id=str(customer.id),
                    source="workflow",
                )
            )
    db.flush()
    by_position = {row.position: row for row in created}
    for item, milestone in zip(items, created, strict=False):
        if item.depends_on_position and item.depends_on_position in by_position:
            milestone.depends_on_id = by_position[item.depends_on_position].id
    customer.onboarding_started_at = customer.onboarding_started_at or datetime.now(UTC)
    set_lifecycle(customer, "ONBOARDING")
    plan.status = "KICKOFF_PENDING"
    if missing_owner:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="customer",
            entity_id=str(customer.id),
            state="BLOCKED",
            last_action="onboarding_started",
            next_action="assign_owner",
            blocked_reason="BLOCKED BY CONFIGURATION",
        )
    else:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="customer",
            entity_id=str(customer.id),
            state="ONBOARDING",
            last_action="onboarding_started",
            next_action="complete_kickoff",
            blocked_reason="",
        )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="onboarding.started",
        entity_type="customer",
        entity_id=str(customer.id),
        payload={"plan_id": str(plan.id), "template": template.key},
    )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="customer",
        entity_id=str(customer.id),
        activity_type="onboarding",
        title="Onboarding started",
        body=f"Template {template.key} created {len(created)} milestones.",
        actor_type="ai",
    )
    return plan


def time_to_value(customer: Customer) -> dict:
    start = customer.activated_at or customer.created_at
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)

    def days(value: datetime | None) -> int | None:
        if value is None or start is None:
            return None
        current = value if value.tzinfo else value.replace(tzinfo=UTC)
        return max((current - start).days, 0)

    return {
        "days_to_kickoff": days(customer.onboarding_started_at),
        "days_to_go_live": days(customer.go_live_at),
        "days_to_first_value": days(customer.first_value_at),
        "days_to_onboarding_complete": days(customer.onboarding_completed_at),
    }


def reconcile_onboarding(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer) -> dict:
    plan = db.scalar(
        select(OnboardingPlan).where(
            OnboardingPlan.tenant_id == tenant_id,
            OnboardingPlan.customer_id == customer.id,
            OnboardingPlan.deleted_at.is_(None),
        )
    )
    if plan is None:
        return {"overdue": 0, "blocked": 0}
    milestones = db.scalars(
        select(OnboardingMilestone).where(OnboardingMilestone.plan_id == plan.id, OnboardingMilestone.deleted_at.is_(None))
    ).all()
    overdue = 0
    blocked = 0
    today = date.today()
    for row in milestones:
        if row.status in {"done", "completed"}:
            continue
        if row.owner_id is None:
            blocked += 1
            row.status = "blocked"
            continue
        if row.depends_on_id:
            parent = db.get(OnboardingMilestone, row.depends_on_id)
            if parent and parent.status not in {"done", "completed"}:
                blocked += 1
                continue
        if row.due_date and row.due_date < today:
            overdue += 1
            emit_event(
                db,
                tenant_id=tenant_id,
                event_type="onboarding.milestone_due",
                entity_type="customer",
                entity_id=str(customer.id),
                payload={"milestone_id": str(row.id), "title": row.title},
            )
    done = [row for row in milestones if row.status in {"done", "completed"}]
    if milestones and len(done) == len(milestones) and plan.status != "ONBOARDING_COMPLETE":
        plan.status = "ONBOARDING_COMPLETE"
        customer.onboarding_completed_at = datetime.now(UTC)
        set_lifecycle(customer, "ACTIVE")
        emit_event(
            db,
            tenant_id=tenant_id,
            event_type="onboarding.completed",
            entity_type="customer",
            entity_id=str(customer.id),
            payload={"plan_id": str(plan.id)},
        )
    elif overdue or blocked:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="customer",
            entity_id=str(customer.id),
            state="BLOCKED" if blocked and not any(row.owner_id for row in milestones) else "ONBOARDING",
            last_action="onboarding_reconcile",
            next_action="resolve_onboarding_delay",
            blocked_reason="BLOCKED BY CONFIGURATION" if blocked and not any(row.owner_id for row in milestones) else "",
        )
    return {"overdue": overdue, "blocked": blocked, "done": len(done)}
