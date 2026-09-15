import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.crm import Account, Activity, Customer, Task
from app.models.lifecycle import Conversation, HealthScore, MeetingRecord, OnboardingMilestone, OnboardingPlan
from app.models.post_sale import HealthScoreSnapshot, ProductUsageSnapshot, SuccessPlanObjective
from app.providers.finance import get_finance_provider
from app.providers.support import get_support_provider
from app.providers.usage import get_usage_provider
from app.services.ai_artifacts import fingerprint
from app.services.audit import emit_event
from app.services.autopilot_settings import get_or_create_settings
from app.services.finance_ingest import latest_finance
from app.services.market import clamp
from app.services.ml_labels import record_features
from app.services.provider_metrics import HEALTH_RECALCS, STALE_DATA
from app.services.query import get_owned
from app.services.support_ingest import customer_support_metrics, latest_support
from app.services.usage_ingest import freshness_state, latest_rollup

RULESET = "rules-v2"
DEFINED_COMPONENTS = (
    "onboarding",
    "usage",
    "adoption",
    "support",
    "engagement",
    "commercial",
    "success",
    "relationship",
)
WEIGHTS = {
    "onboarding": 12,
    "usage": 16,
    "adoption": 12,
    "support": 12,
    "engagement": 12,
    "commercial": 16,
    "success": 10,
    "relationship": 10,
}
THRESHOLDS = (50, 70)
ELIGIBLE = {"LIVE"}


def persist_usage(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, account: Account) -> ProductUsageSnapshot:
    snap = get_usage_provider(db, tenant_id).snapshot(account_name=account.name)
    row = ProductUsageSnapshot(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer.id,
        account_id=account.id,
        period_start=datetime.now(UTC).date(),
        active_users=snap.active_users,
        seats_licensed=snap.seats_licensed,
        seats_used=snap.seats_used,
        frequency=snap.frequency,
        feature_breadth=snap.feature_breadth,
        depth=snap.depth,
        trend=snap.trend,
        last_activity_at=snap.last_activity_at,
        provider=snap.provider,
        is_mock=snap.is_mock,
        evidence=snap.evidence,
    )
    db.add(row)
    db.flush()
    return row


def _engagement(db: Session, tenant_id: UUID, customer: Customer) -> tuple[int, str]:
    since = datetime.now(UTC) - timedelta(days=30)
    meetings = db.scalar(
        select(func.count()).where(
            MeetingRecord.tenant_id == tenant_id,
            MeetingRecord.account_id == customer.account_id,
            MeetingRecord.deleted_at.is_(None),
            MeetingRecord.created_at >= since,
        )
    ) or 0
    emails = db.scalar(
        select(func.count()).where(
            Activity.tenant_id == tenant_id,
            Activity.entity_type.in_(["customer", "account"]),
            Activity.entity_id.in_([str(customer.id), str(customer.account_id)]),
            Activity.activity_type.in_(["email", "meeting", "call"]),
            Activity.deleted_at.is_(None),
            Activity.created_at >= since,
        )
    ) or 0
    conversations = db.scalar(
        select(func.count()).where(
            Conversation.tenant_id == tenant_id,
            Conversation.account_id == customer.account_id,
            Conversation.deleted_at.is_(None),
            Conversation.created_at >= since,
        )
    ) or 0
    score = clamp(int(meetings) * 18 + int(emails) * 8 + int(conversations) * 6)
    return score, f"30d meetings={meetings} emails={emails} conversations={conversations}"


def _component(score: int | None, status: str, weight: int, freshness: str, source: str, evidence: str, reasons: list[str] | None = None) -> dict:
    return {
        "score": score,
        "status": status,
        "weight": weight,
        "freshness": freshness,
        "source": source,
        "evidence": evidence,
        "reasons": reasons or [],
    }


def _risk_category(total: int) -> str:
    if total < THRESHOLDS[0]:
        return "at_risk"
    if total < THRESHOLDS[1]:
        return "watch"
    return "healthy"


def _threshold_crossed(previous: int | None, current: int) -> bool:
    if previous is None:
        return False
    for mark in THRESHOLDS:
        if (previous < mark <= current) or (current < mark <= previous):
            return True
    return False


def recalculate(db: Session, tenant_id: UUID, customer: Customer, actor_id: UUID | None = None) -> HealthScore:
    account = get_owned(db, Account, tenant_id, customer.account_id)
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    usage_provider = get_usage_provider(db, tenant_id)
    support_provider = get_support_provider(db, tenant_id)
    finance_provider = get_finance_provider(db, tenant_id)
    rollup = latest_rollup(db, tenant_id, customer.id)
    support_row = latest_support(db, tenant_id, customer.id)
    finance_row = latest_finance(db, tenant_id, customer.id)
    if rollup is None and not settings.usage_live_enabled:
        persist_usage(db, tenant_id=tenant_id, actor_id=actor_id or customer.created_by or customer.id, customer=customer, account=account)

    plan = db.scalar(
        select(OnboardingPlan).where(
            OnboardingPlan.tenant_id == tenant_id,
            OnboardingPlan.customer_id == customer.id,
            OnboardingPlan.deleted_at.is_(None),
        )
    )
    milestones = []
    if plan:
        milestones = db.scalars(
            select(OnboardingMilestone).where(OnboardingMilestone.plan_id == plan.id, OnboardingMilestone.deleted_at.is_(None))
        ).all()
    done = sum(1 for row in milestones if row.status in {"done", "completed"})
    onboarding_score = 55 if not milestones else clamp(int(done / len(milestones) * 100))
    open_tasks = db.scalar(
        select(func.count()).where(
            Task.tenant_id == tenant_id,
            Task.entity_type == "customer",
            Task.entity_id == str(customer.id),
            Task.status == "open",
        )
    ) or 0
    engagement, engagement_reason = _engagement(db, tenant_id, customer)
    if engagement == 0:
        engagement = clamp(70 - int(open_tasks) * 12)
        engagement_reason = f"Open customer tasks={open_tasks}"
    commercial = 80 if customer.arr and customer.arr > 0 else 35
    relationship = 78 if account.ownership == "customer" else 40
    objectives = db.scalars(
        select(SuccessPlanObjective).where(
            SuccessPlanObjective.tenant_id == tenant_id,
            SuccessPlanObjective.customer_id == customer.id,
            SuccessPlanObjective.deleted_at.is_(None),
        )
    ).all()
    if objectives:
        met = sum(1 for row in objectives if row.status in {"met", "done", "completed"})
        success_score = clamp(int(met / len(objectives) * 100))
        success_evidence = f"{met}/{len(objectives)} success objectives"
    elif customer.onboarding_completed_at:
        success_score = 72
        success_evidence = "Onboarding completed; success plan still thin"
    else:
        success_score = 48
        success_evidence = "Success outcomes not yet evidenced"

    components: dict[str, dict] = {
        "onboarding": _component(onboarding_score, "LIVE", WEIGHTS["onboarding"], "SUFFICIENT", "crm", f"{done}/{len(milestones)} milestones"),
        "engagement": _component(engagement, "LIVE", WEIGHTS["engagement"], "SUFFICIENT", "crm", engagement_reason),
        "commercial": _component(commercial, "LIVE", WEIGHTS["commercial"], "SUFFICIENT", "crm", f"ARR={customer.arr}"),
        "relationship": _component(relationship, "LIVE", WEIGHTS["relationship"], "SUFFICIENT", "crm", f"ownership={account.ownership}"),
        "success": _component(success_score, "LIVE", WEIGHTS["success"], "SUFFICIENT", "crm", success_evidence),
    }
    reasons: list[str] = []

    if rollup is not None and not rollup.is_mock:
        usage_state = freshness_state(rollup.last_activity_at, settings.usage_freshness_hours)
        if usage_state == "STALE":
            STALE_DATA.labels(component="usage").inc()
            components["usage"] = _component(None, "STALE", WEIGHTS["usage"], "STALE", "usage", rollup.evidence, ["USAGE_STALE"])
            components["adoption"] = _component(None, "STALE", WEIGHTS["adoption"], "STALE", "usage", rollup.evidence, ["ADOPTION_STALE"])
        else:
            usage_score = clamp(rollup.dau * 8 + rollup.wau * 3)
            if rollup.trend_30d == "declining":
                usage_score = max(usage_score - 20, 10)
                reasons.append("USAGE_DECLINING")
            adoption_score = clamp(rollup.feature_breadth * 12 + min(rollup.feature_depth, 40))
            if rollup.utilization_pct is not None and rollup.utilization_pct < settings.low_utilization_pct:
                adoption_score = min(adoption_score, 35)
                reasons.append("LOW_UTILIZATION")
            components["usage"] = _component(usage_score, "LIVE", WEIGHTS["usage"], "SUFFICIENT", "usage", rollup.evidence)
            components["adoption"] = _component(adoption_score, "LIVE", WEIGHTS["adoption"], "SUFFICIENT", "usage", rollup.evidence)
    elif settings.usage_live_enabled:
        components["usage"] = _component(None, "NOT_CONFIGURED", WEIGHTS["usage"], "NOT_CONFIGURED", "usage", "LIVE usage enabled but no events for this customer")
        components["adoption"] = _component(None, "NOT_CONFIGURED", WEIGHTS["adoption"], "NOT_CONFIGURED", "usage", "No live adoption rollup")
    else:
        usage = usage_provider.snapshot(account_name=account.name)
        components["usage"] = _component(None, "MOCK", WEIGHTS["usage"], "MOCK", usage.provider, usage.evidence)
        components["adoption"] = _component(None, "MOCK", WEIGHTS["adoption"], "MOCK", usage.provider, usage.evidence)

    if support_row is not None and not support_row.is_mock:
        metrics = customer_support_metrics(db, tenant_id, customer.id)
        support_state = freshness_state(metrics["last_event_at"], settings.support_freshness_hours)
        if support_state == "STALE":
            STALE_DATA.labels(component="support").inc()
            components["support"] = _component(None, "STALE", WEIGHTS["support"], "STALE", "support", support_row.evidence, ["SUPPORT_STALE"])
        else:
            critical = int(metrics["open_critical"] or 0)
            open_total = int(metrics["open_total"] or 0)
            support_score = clamp(90 - critical * 25 - min(open_total, 8) * 4)
            support_reasons = []
            if critical:
                support_reasons.append("HIGH_SUPPORT_SEVERITY")
                reasons.append("HIGH_SUPPORT_SEVERITY")
            components["support"] = _component(support_score, "LIVE", WEIGHTS["support"], "SUFFICIENT", "support", support_row.evidence, support_reasons)
    elif settings.support_live_enabled:
        components["support"] = _component(None, "NOT_CONFIGURED", WEIGHTS["support"], "NOT_CONFIGURED", "support", "LIVE support enabled but no tickets")
    else:
        support = support_provider.snapshot(account_name=account.name)
        components["support"] = _component(None, "NOT_CONFIGURED", WEIGHTS["support"], "NOT_CONFIGURED", support.provider, support.evidence)

    if finance_row is not None and not finance_row.is_mock:
        finance_state = freshness_state(finance_row.last_event_at, settings.finance_freshness_hours)
        if finance_state == "STALE":
            STALE_DATA.labels(component="finance").inc()
        elif finance_row.days_past_due and finance_row.days_past_due > 0:
            commercial = max(commercial - 30, 15)
            reasons.append("PAYMENT_OVERDUE")
            components["commercial"]["score"] = commercial
            components["commercial"]["evidence"] = finance_row.evidence
            components["commercial"]["source"] = "finance"
            components["commercial"]["reasons"] = ["PAYMENT_OVERDUE"]
        elif finance_row.credit_hold:
            commercial = max(commercial - 20, 20)
            reasons.append("CREDIT_HOLD")
            components["commercial"]["score"] = commercial
    elif settings.finance_live_enabled:
        components["commercial"]["evidence"] = f"{components['commercial']['evidence']}; finance LIVE but no snapshot"

    eligible = {
        name: row
        for name, row in components.items()
        if row.get("status") in ELIGIBLE and row.get("freshness") == "SUFFICIENT" and row.get("score") is not None
    }
    weight_sum = sum(int(row["weight"]) for row in eligible.values()) or 1
    total = clamp(int(round(sum(int(row["score"]) * int(row["weight"]) for row in eligible.values()) / weight_sum)))
    coverage = int(round(len(eligible) / len(DEFINED_COMPONENTS) * 100))
    unavailable = [name for name, row in components.items() if row.get("status") not in ELIGIBLE]
    reason_codes = reasons + [name.upper() + "_" + str(row.get("status")) for name, row in components.items() if row.get("status") not in ELIGIBLE]
    reasons_text = "; ".join(f"{name}={row['status']}" for name, row in components.items())
    input_fp = fingerprint({"components": components, "arr": str(customer.arr), "milestones": done, "ruleset": RULESET})
    previous = db.scalar(
        select(HealthScoreSnapshot)
        .where(
            HealthScoreSnapshot.tenant_id == tenant_id,
            HealthScoreSnapshot.customer_id == customer.id,
            HealthScoreSnapshot.ruleset_version == RULESET,
        )
        .order_by(HealthScoreSnapshot.created_at.desc())
    )
    trend = "stable"
    if previous is not None:
        if total > previous.total + 4:
            trend = "improving"
        elif total < previous.total - 4:
            trend = "declining"
    now = datetime.now(UTC)
    payload = dict(
        total=total,
        adoption=int(components.get("adoption", {}).get("score") or 0),
        usage=int(components.get("usage", {}).get("score") or 0),
        engagement=engagement,
        commercial=commercial,
        relationship=relationship,
        onboarding=onboarding_score,
        reasons=reasons_text,
        version=RULESET,
        components_json=json.dumps(components, default=str),
        reason_codes_json=json.dumps(reason_codes),
        unavailable_components=",".join(unavailable),
        calculated_at=now,
        data_freshness="live-rules",
        trend=trend,
        health_data_coverage=coverage,
    )
    row = db.scalar(select(HealthScore).where(HealthScore.tenant_id == tenant_id, HealthScore.customer_id == customer.id, HealthScore.deleted_at.is_(None)))
    previous_total = row.total if row is not None else None
    previous_category = _risk_category(row.total) if row is not None else None
    previous_components = {}
    if row is not None:
        try:
            previous_components = json.loads(row.components_json or "{}")
        except json.JSONDecodeError:
            previous_components = {}
    material = False
    for name, current in components.items():
        prior = previous_components.get(name) or {}
        if prior.get("status") != current.get("status"):
            material = True
            break
    category = _risk_category(total)
    emit = (
        row is None
        or _threshold_crossed(previous_total, total)
        or material
        or previous_category != category
        or (previous is not None and abs(total - previous.total) >= 4 and trend != "stable")
    )
    if row is None:
        row = HealthScore(tenant_id=tenant_id, created_by=actor_id, customer_id=customer.id, **payload)
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    customer.health_trend = trend
    if previous is None or previous.input_fingerprint != input_fp:
        db.add(
            HealthScoreSnapshot(
                tenant_id=tenant_id,
                created_by=actor_id,
                customer_id=customer.id,
                total=total,
                components_json=payload["components_json"],
                reason_codes_json=payload["reason_codes_json"],
                unavailable_components=payload["unavailable_components"],
                ruleset_version=RULESET,
                data_freshness="live-rules",
                trend=trend,
                input_fingerprint=input_fp,
                calculated_at=now,
                health_data_coverage=coverage,
            )
        )
    if emit:
        emit_event(
            db,
            tenant_id=tenant_id,
            event_type="customer.health_changed",
            entity_type="customer",
            entity_id=str(customer.id),
            payload={"total": total, "trend": trend, "version": RULESET, "coverage": coverage, "category": category},
        )
    record_features(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        customer_id=customer.id,
        entity_type="customer",
        entity_id=str(customer.id),
        features={
            "customer_health_score": total,
            "coverage": coverage,
            "usage_status": components["usage"]["status"],
            "support_status": components["support"]["status"],
            "commercial": commercial,
        },
        ruleset_version=RULESET,
        task_key="CUSTOMER_CHURN",
    )
    from app.services.ml.prediction import maybe_shadow

    maybe_shadow(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        task_key="CUSTOMER_CHURN",
        entity_type="customer",
        entity_id=str(customer.id),
    )
    record_features(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        customer_id=customer.id,
        entity_type="customer",
        entity_id=str(customer.id),
        features={
            "customer_health_score": total,
            "coverage": coverage,
            "usage_status": components["usage"]["status"],
            "support_status": components["support"]["status"],
            "commercial": commercial,
        },
        ruleset_version=RULESET,
        task_key="CUSTOMER_RENEWAL",
    )
    HEALTH_RECALCS.labels(ruleset=RULESET).inc()
    _ = finance_provider
    return row
