from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.autonomy import EntityAutomationState
from app.models.crm import Customer, Renewal
from app.models.identity import DomainEvent
from app.models.lifecycle import AdvocacyAsset, OnboardingMilestone, OnboardingPlan
from app.models.post_sale import ExpansionRecommendation
from app.models.signals import CustomerIntelligenceState
from app.schemas.post_sale import LifecycleLaneOut, PostSaleAttentionOut
from app.services.advocacy import evaluate_advocacy
from app.services.audit import emit_event
from app.services.automation_state import is_entity_paused
from app.services.autopilot_settings import get_or_create_settings
from app.services.customer_health import recalculate
from app.services.customer_intelligence import process_dirty_customers
from app.services.customer_risk import detect_risks
from app.services.expansion import detect_expansion, growth_plan
from app.services.onboarding import reconcile_onboarding
from app.services.qbr import next_qbr_date, prepare_qbr, qbr_period
from app.services.renewal import emit_windows, parse_windows, score_readiness


def _customers(db: Session, tenant_id: UUID) -> list[Customer]:
    return list(db.scalars(select(Customer).where(Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None))).all())


def reconcile_frequent(db: Session, *, tenant_id: UUID, actor_id: UUID) -> dict:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    overdue = 0
    risks = 0
    process_dirty_customers(db, tenant_id=tenant_id, actor_id=actor_id)
    for customer in _customers(db, tenant_id):
        if is_entity_paused(db, tenant_id=tenant_id, entity_type="customer", entity_id=str(customer.id)):
            continue
        result = reconcile_onboarding(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer)
        overdue += result.get("overdue", 0)
        if settings.customer_success_enabled:
            found = detect_risks(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer)
            risks += len(found)
    return {"overdue_milestones": overdue, "risks": risks}


def reconcile_daily(db: Session, *, tenant_id: UUID, actor_id: UUID) -> dict:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    health = 0
    windows = 0
    expansion = 0
    for customer in _customers(db, tenant_id):
        if is_entity_paused(db, tenant_id=tenant_id, entity_type="customer", entity_id=str(customer.id)):
            continue
        if settings.customer_health_enabled:
            state = db.scalar(
                select(CustomerIntelligenceState).where(
                    CustomerIntelligenceState.tenant_id == tenant_id,
                    CustomerIntelligenceState.customer_id == customer.id,
                    CustomerIntelligenceState.deleted_at.is_(None),
                )
            )
            if state is None or state.dirty or state.last_recalc_at is None:
                recalculate(db, tenant_id, customer, actor_id)
                health += 1
        renewal = db.scalar(select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None)))
        if renewal and settings.renewal_enabled:
            opened = emit_windows(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                customer=customer,
                renewal=renewal,
                windows=parse_windows(settings.renewal_windows),
            )
            windows += len(opened)
            score_readiness(db, tenant_id=tenant_id, customer=customer, renewal=renewal)
        if settings.expansion_enabled or settings.upsell_enabled or settings.cross_sell_enabled:
            recs = detect_expansion(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, settings=settings)
            expansion += len(recs)
        due = next_qbr_date(customer)
        if settings.qbr_automation_enabled and 0 <= (due - date.today()).days <= 14:
            emit_event(
                db,
                tenant_id=tenant_id,
                event_type="qbr.upcoming",
                entity_type="customer",
                entity_id=str(customer.id),
                payload={"period": qbr_period(due), "due": due.isoformat()},
            )
    from app.services.lifecycle import build_forecast
    from app.services.ml.evaluate import evaluate_matured

    build_forecast(db, tenant_id, actor_id)
    evaluate_matured(db, tenant_id=tenant_id, actor_id=actor_id)
    return {"health_refreshed": health, "windows": windows, "expansion": expansion}


def reconcile_weekly(db: Session, *, tenant_id: UUID, actor_id: UUID) -> dict:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    advocacy = 0
    qbrs = 0
    for customer in _customers(db, tenant_id):
        if is_entity_paused(db, tenant_id=tenant_id, entity_type="customer", entity_id=str(customer.id)):
            continue
        if settings.advocacy_enabled:
            asset = evaluate_advocacy(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, settings=settings)
            if asset:
                advocacy += 1
        if settings.qbr_automation_enabled:
            due = next_qbr_date(customer)
            if 0 <= (due - date.today()).days <= 21:
                prepare_qbr(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer)
                qbrs += 1
        growth_plan(db, tenant_id=tenant_id, customer=customer)
    return {"advocacy": advocacy, "qbrs": qbrs}


def reconcile_all_tenants(tier: str) -> int:
    from app.db.session import get_engine, get_session
    from app.models.identity import User

    get_engine()
    db = get_session()
    try:
        from app.db.tenant_jobs import run_per_tenant

        def _one(tenant_id):
            settings = get_or_create_settings(db, tenant_id=tenant_id)
            if not settings.enabled:
                return 0
            actor = db.scalar(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)))
            if actor is None:
                return 0
            if tier == "frequent":
                reconcile_frequent(db, tenant_id=tenant_id, actor_id=actor.id)
            elif tier == "daily":
                reconcile_daily(db, tenant_id=tenant_id, actor_id=actor.id)
            else:
                reconcile_weekly(db, tenant_id=tenant_id, actor_id=actor.id)
            return 1

        ran = run_per_tenant(db, _one)
        db.commit()
        return ran
    finally:
        db.close()


def attention(db: Session, tenant_id: UUID) -> PostSaleAttentionOut:
    today = date.today()
    customers = _customers(db, tenant_id)
    health_risk = 0
    onboarding_risk = 0
    for customer in customers:
        if customer.lifecycle_state == "AT_RISK" or customer.health_trend == "declining":
            health_risk += 1
        plan = db.scalar(
            select(OnboardingPlan).where(OnboardingPlan.tenant_id == tenant_id, OnboardingPlan.customer_id == customer.id, OnboardingPlan.deleted_at.is_(None))
        )
        if plan:
            overdue = db.scalar(
                select(func.count()).where(
                    OnboardingMilestone.plan_id == plan.id,
                    OnboardingMilestone.status.notin_(["done", "completed"]),
                    OnboardingMilestone.due_date.is_not(None),
                    OnboardingMilestone.due_date < today,
                )
            ) or 0
            if overdue:
                onboarding_risk += 1
    renewals = db.scalars(select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.deleted_at.is_(None))).all()
    approaching = sum(1 for row in renewals if row.renewal_date and 0 <= (row.renewal_date - today).days <= 90)
    at_risk = sum(1 for row in renewals if row.readiness and row.readiness < 50)
    expansion = db.scalar(
        select(func.count()).where(
            ExpansionRecommendation.tenant_id == tenant_id,
            ExpansionRecommendation.status == "open",
            ExpansionRecommendation.deleted_at.is_(None),
        )
    ) or 0
    advocacy = db.scalar(
        select(func.count()).where(AdvocacyAsset.tenant_id == tenant_id, AdvocacyAsset.status == "identified", AdvocacyAsset.deleted_at.is_(None))
    ) or 0
    from app.models.post_sale import CustomerRisk
    from app.models.signals import UsageRollup

    usage_risk = db.scalar(
        select(func.count()).where(
            CustomerRisk.tenant_id == tenant_id,
            CustomerRisk.status == "open",
            CustomerRisk.risk_type.in_(["ADOPTION_RISK", "USAGE_DECLINE"]),
            CustomerRisk.deleted_at.is_(None),
        )
    ) or 0
    support_risk = db.scalar(
        select(func.count()).where(
            CustomerRisk.tenant_id == tenant_id,
            CustomerRisk.status == "open",
            CustomerRisk.risk_type == "SUPPORT_RISK",
            CustomerRisk.deleted_at.is_(None),
        )
    ) or 0
    commercial_risk = db.scalar(
        select(func.count()).where(
            CustomerRisk.tenant_id == tenant_id,
            CustomerRisk.status == "open",
            CustomerRisk.risk_type == "COMMERCIAL_RISK",
            CustomerRisk.deleted_at.is_(None),
        )
    ) or 0
    high_util = db.scalar(
        select(func.count()).where(
            UsageRollup.tenant_id == tenant_id,
            UsageRollup.deleted_at.is_(None),
            UsageRollup.is_mock.is_(False),
            UsageRollup.freshness_state == "LIVE",
            UsageRollup.utilization_pct.is_not(None),
            UsageRollup.utilization_pct >= 85,
        )
    ) or 0
    return PostSaleAttentionOut(
        customers_requiring_attention=health_risk,
        onboarding_at_risk=onboarding_risk,
        renewals_approaching=approaching,
        renewals_at_risk=at_risk,
        expansion_opportunities=int(expansion),
        advocacy_candidates=int(advocacy),
        usage_risk=int(usage_risk),
        support_risk=int(support_risk),
        commercial_risk=int(commercial_risk),
        high_utilization_candidates=int(high_util),
    )


def lifecycle_lanes(db: Session, tenant_id: UUID) -> list[LifecycleLaneOut]:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    mapping = {
        "ACQUIRE": ["DISCOVERED", "ENRICHING", "ENRICHED", "SCORING", "SCORED", "QUALIFYING", "QUALIFIED"],
        "SELL": ["RESEARCHING", "READY_FOR_OUTREACH", "OUTREACH_APPROVAL_PENDING", "CONTACTED", "MEETING_SCHEDULED"],
        "SUCCEED": ["ONBOARDING", "IMPLEMENTING", "ADOPTING", "NEW_CUSTOMER"],
        "RETAIN": ["ACTIVE", "AT_RISK", "RENEWAL_UPCOMING", "RENEWAL_IN_PROGRESS"],
        "GROW": ["EXPANSION"],
        "ADVOCATE": ["RENEWED"],
    }
    rows = []
    for lane, states in mapping.items():
        running = db.scalar(
            select(func.count()).where(
                EntityAutomationState.tenant_id == tenant_id,
                EntityAutomationState.deleted_at.is_(None),
                EntityAutomationState.state.in_(states),
                EntityAutomationState.paused_at.is_(None),
            )
        ) or 0
        waiting = db.scalar(
            select(func.count()).where(
                EntityAutomationState.tenant_id == tenant_id,
                EntityAutomationState.state == "OUTREACH_APPROVAL_PENDING",
                EntityAutomationState.deleted_at.is_(None),
            )
        ) or 0 if lane == "SELL" else 0
        blocked = db.scalar(
            select(func.count()).where(
                EntityAutomationState.tenant_id == tenant_id,
                EntityAutomationState.state == "BLOCKED",
                EntityAutomationState.deleted_at.is_(None),
            )
        ) or 0
        completed = db.scalar(
            select(func.count()).where(
                DomainEvent.tenant_id == tenant_id,
                DomainEvent.created_at >= start,
                DomainEvent.event_type.in_(
                    {
                        "ACQUIRE": ["lead.qualified"],
                        "SELL": ["email.sent", "meeting.booked"],
                        "SUCCEED": ["onboarding.completed", "handoff.created"],
                        "RETAIN": ["renewal.window_opened", "renewal.prepared"],
                        "GROW": ["expansion.detected", "upsell.detected", "cross_sell.detected"],
                        "ADVOCATE": ["advocacy.eligible"],
                    }[lane]
                ),
            )
        ) or 0
        failed = 0
        rows.append(
            LifecycleLaneOut(
                lane=lane,
                running=int(running),
                waiting=int(waiting),
                blocked=int(blocked) if lane in {"SUCCEED", "RETAIN"} else 0,
                completed_today=int(completed),
                failed=failed,
            )
        )
    _ = timedelta
    return rows
