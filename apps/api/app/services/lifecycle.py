import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.crm import Account, Activity, Contact, Customer, Lead, Opportunity, Renewal, Task
from app.models.lifecycle import (
    AdvocacyAsset,
    Campaign,
    Conversation,
    DealInsight,
    ForecastSnapshot,
    HealthScore,
    MeetingRecord,
    OnboardingMilestone,
    OnboardingPlan,
    Playbook,
    Product,
    Quote,
    QuoteLine,
    Sequence,
    SequenceEnrollment,
    SequenceStep,
    SuccessPlan,
    WhitespaceCell,
)
from app.models.market import CompetitiveSignal
from app.models.workflow import WorkflowRun
from app.providers.usage import get_usage_provider
from app.services.crm import add_activity
from app.services.market import clamp
from app.services.query import get_owned


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def quote_totals(subtotal: Decimal, discount_pct: int, tax_pct: int) -> tuple[Decimal, Decimal, bool]:
    discount_pct = max(0, min(100, discount_pct))
    tax_pct = max(0, min(100, tax_pct))
    discounted = subtotal * Decimal(100 - discount_pct) / Decimal(100)
    total = (discounted * Decimal(100 + tax_pct) / Decimal(100)).quantize(Decimal("0.01"))
    return discounted.quantize(Decimal("0.01")), total, discount_pct >= 10


def recompute_quote(db: Session, quote: Quote) -> Quote:
    lines = db.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id, QuoteLine.deleted_at.is_(None))).all()
    subtotal = sum((line.line_total for line in lines), Decimal("0"))
    _discounted, total, approval = quote_totals(subtotal, quote.discount_pct, quote.tax_pct)
    quote.subtotal = subtotal
    quote.total = total
    quote.approval_required = approval
    return quote


def score_deal(db: Session, tenant_id: UUID, opportunity: Opportunity) -> DealInsight:
    contacts = db.scalars(
        select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.account_id == opportunity.account_id,
            Contact.deleted_at.is_(None),
        )
    ).all()
    roles = {row.buying_role for row in contacts}
    missing_buyer = "economic_buyer" not in roles and "decision_maker" not in roles
    weak_champion = "champion" not in roles
    missing_next = not (opportunity.next_step or "").strip()
    close_slip = bool(opportunity.expected_close and opportunity.expected_close < date.today() and opportunity.stage not in {"closed_won", "closed_lost"})
    latest_activity = db.scalar(
        select(func.max(Activity.created_at)).where(
            Activity.tenant_id == tenant_id,
            Activity.entity_type == "opportunity",
            Activity.entity_id == str(opportunity.id),
        )
    )
    last_seen = _aware(latest_activity)
    stall = last_seen is None or (datetime.now(UTC) - last_seen).days >= 14
    competitor = db.scalar(
        select(func.count()).where(
            CompetitiveSignal.tenant_id == tenant_id,
            CompetitiveSignal.account_id == opportunity.account_id,
            CompetitiveSignal.deleted_at.is_(None),
        )
    ) or 0
    competitor_risk = int(competitor) > 0
    risk = 8
    reasons = []
    if missing_buyer:
        risk += 18
        reasons.append("No economic buyer or decision maker on the committee.")
    if weak_champion:
        risk += 12
        reasons.append("No champion recorded.")
    if missing_next:
        risk += 16
        reasons.append("Next step is empty.")
    if close_slip:
        risk += 22
        reasons.append("Expected close is in the past.")
    if stall:
        risk += 14
        reasons.append("No opportunity activity in 14 days.")
    if competitor_risk:
        risk += 12
        reasons.append("Competitive signal exists on the account.")
    insight = db.scalar(
        select(DealInsight).where(
            DealInsight.tenant_id == tenant_id,
            DealInsight.opportunity_id == opportunity.id,
            DealInsight.deleted_at.is_(None),
        )
    )
    payload = dict(
        risk_score=clamp(risk),
        missing_buyer=missing_buyer,
        weak_champion=weak_champion,
        stall=stall,
        close_slip=close_slip,
        competitor_risk=competitor_risk,
        missing_next_step=missing_next,
        reasons=" ".join(reasons) or "No material risk flags under rules-v1.",
        version="rules-v1",
    )
    if insight is None:
        insight = DealInsight(tenant_id=tenant_id, opportunity_id=opportunity.id, **payload)
        db.add(insight)
    else:
        for key, value in payload.items():
            setattr(insight, key, value)
    return insight


def build_forecast(db: Session, tenant_id: UUID, actor_id: UUID) -> ForecastSnapshot:
    open_rows = db.scalars(
        select(Opportunity).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.stage.notin_(["closed_won", "closed_lost"]),
        )
    ).all()
    won = db.scalar(
        select(func.count()).where(Opportunity.tenant_id == tenant_id, Opportunity.stage == "closed_won", Opportunity.deleted_at.is_(None))
    ) or 0
    lost = db.scalar(
        select(func.count()).where(Opportunity.tenant_id == tenant_id, Opportunity.stage == "closed_lost", Opportunity.deleted_at.is_(None))
    ) or 0
    decided = int(won) + int(lost)
    pipeline = sum((row.amount or Decimal("0")) for row in open_rows)
    weighted = sum((row.amount or Decimal("0")) * Decimal(row.probability) / Decimal(100) for row in open_rows)
    committed = sum((row.amount or Decimal("0")) for row in open_rows if row.stage in {"commit", "legal", "procurement"})
    snapshot = ForecastSnapshot(
        tenant_id=tenant_id,
        created_by=actor_id,
        period=date.today().strftime("%Y-%m"),
        committed=committed,
        best_case=pipeline,
        pipeline=pipeline,
        weighted=weighted,
        win_rate=Decimal(str(round(float(won) / decided, 4))) if decided else Decimal("0"),
        version="rules-v1",
    )
    db.add(snapshot)
    return snapshot


def score_health(db: Session, tenant_id: UUID, customer: Customer) -> HealthScore:
    account = get_owned(db, Account, tenant_id, customer.account_id)
    usage = get_usage_provider().snapshot(account_name=account.name)
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
    done = sum(1 for row in milestones if row.status == "done")
    onboarding = 20 if not milestones else clamp(int(done / len(milestones) * 20))
    open_tasks = db.scalar(
        select(func.count()).where(
            Task.tenant_id == tenant_id,
            Task.entity_type == "customer",
            Task.entity_id == str(customer.id),
            Task.status == "open",
        )
    ) or 0
    engagement = clamp(20 - int(open_tasks) * 4)
    commercial = 18 if customer.arr and customer.arr > 0 else 6
    relationship = 16 if account.ownership == "customer" else 8
    adoption = clamp(usage.adoption // 5)
    usage_score = clamp(usage.usage // 5)
    total = clamp(onboarding + engagement + commercial + relationship + adoption + usage_score)
    reasons = f"Onboarding {onboarding}/20; engagement {engagement}/20; commercial {commercial}; usage {usage.provider} ({usage.evidence})"
    row = db.scalar(
        select(HealthScore).where(HealthScore.tenant_id == tenant_id, HealthScore.customer_id == customer.id, HealthScore.deleted_at.is_(None))
    )
    payload = dict(
        total=total,
        adoption=adoption,
        usage=usage_score,
        engagement=engagement,
        commercial=commercial,
        relationship=relationship,
        onboarding=onboarding,
        reasons=reasons,
        version="rules-v1",
    )
    if row is None:
        row = HealthScore(tenant_id=tenant_id, customer_id=customer.id, **payload)
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    return row


def ensure_post_sale(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, account_name: str) -> None:
    plan = db.scalar(
        select(OnboardingPlan).where(OnboardingPlan.tenant_id == tenant_id, OnboardingPlan.customer_id == customer.id)
    )
    if plan is None:
        plan = OnboardingPlan(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=customer.id,
            status="planned",
            objective=f"Land value for {account_name} in the first 90 days.",
        )
        db.add(plan)
        db.flush()
        for title, days in (("Kickoff", 7), ("Data workshop", 21), ("First outcome review", 60)):
            db.add(
                OnboardingMilestone(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    plan_id=plan.id,
                    title=title,
                    due_date=date.today() + timedelta(days=days),
                )
            )
    if db.scalar(select(SuccessPlan).where(SuccessPlan.tenant_id == tenant_id, SuccessPlan.customer_id == customer.id)) is None:
        db.add(
            SuccessPlan(
                tenant_id=tenant_id,
                created_by=actor_id,
                customer_id=customer.id,
                objective="Governed AI outcomes with an executive sponsor.",
                status="active",
            )
        )
    score_health(db, tenant_id, customer)


def enroll_sequence(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    sequence: Sequence,
    lead: Lead,
    run_id: UUID | None = None,
    actor_type: str = "human",
) -> SequenceEnrollment:
    if lead.opt_out:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lead has opted out")
    if sequence.channel == "email" and not lead.consent_email:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email consent is required to enroll")
    existing = db.scalar(
        select(SequenceEnrollment).where(
            SequenceEnrollment.tenant_id == tenant_id,
            SequenceEnrollment.sequence_id == sequence.id,
            SequenceEnrollment.lead_id == lead.id,
            SequenceEnrollment.status == "active",
        )
    )
    if existing:
        return existing
    enrollment = SequenceEnrollment(
        tenant_id=tenant_id,
        created_by=actor_id,
        sequence_id=sequence.id,
        lead_id=lead.id,
        status="active",
        current_step=1,
        next_run_at=datetime.now(UTC),
    )
    db.add(enrollment)
    db.flush()
    first = db.scalar(
        select(SequenceStep)
        .where(SequenceStep.sequence_id == sequence.id, SequenceStep.deleted_at.is_(None))
        .order_by(SequenceStep.position.asc())
    )
    if first and first.action_type == "email_draft":
        key = f"sequence.email.send:{lead.id}:{enrollment.id}"
        already = db.scalar(
            select(AIApproval).where(
                AIApproval.tenant_id == tenant_id,
                AIApproval.idempotency_key == key,
                AIApproval.deleted_at.is_(None),
            )
        )
        if already is None:
            db.add(
                AIApproval(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    action_level=2,
                    action_type="sequence.email.send",
                    title=f"Send sequence step for {lead.email}",
                    payload_json=json.dumps(
                        {
                            "enrollment_id": str(enrollment.id),
                            "lead_id": str(lead.id),
                            "sequence_id": str(sequence.id),
                            "run_id": str(run_id) if run_id else "",
                            "template": first.template,
                            "subject": "Follow-up",
                            "body": first.template,
                            "why": "Qualified lead selected for the first eligible email sequence.",
                            "evidence": "Consent on file. Deterministic score met the tenant minimum.",
                            "risk": "External send. Mock provider until Gmail is connected.",
                            "expected_outcome": "First-touch email recorded after approval.",
                        }
                    ),
                    status="pending",
                    run_id=run_id,
                    entity_type="lead",
                    entity_id=str(lead.id),
                    idempotency_key=key,
                )
            )
    elif first and first.action_type == "task":
        db.add(
            Task(
                tenant_id=tenant_id,
                created_by=actor_id,
                title=f"Sequence: {sequence.name}",
                description=first.template,
                status="open",
                priority="medium",
                entity_type="lead",
                entity_id=str(lead.id),
                source="workflow",
            )
        )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="sequence",
        title=f"Enrolled in {sequence.name}",
        body="Send stays in Approvals until a human approves.",
        actor_type=actor_type,
    )
    return enrollment


def run_playbook(db: Session, *, tenant_id: UUID, actor_id: UUID, playbook: Playbook, entity_type: str, entity_id: str) -> WorkflowRun:
    actions = json.loads(playbook.actions_json or "[]")
    log = []
    for action in actions:
        kind = action.get("type")
        if kind == "create_task":
            db.add(
                Task(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    title=action.get("title", playbook.name),
                    description=action.get("body", ""),
                    status="open",
                    priority=action.get("priority", "medium"),
                    entity_type=entity_type,
                    entity_id=entity_id,
                    source="workflow",
                )
            )
            log.append({"type": kind, "ok": True})
        elif kind == "write_activity":
            add_activity(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entity_type=entity_type,
                entity_id=entity_id,
                activity_type="playbook",
                title=action.get("title", playbook.name),
                body=action.get("body", ""),
                actor_type="ai",
            )
            log.append({"type": kind, "ok": True})
        elif kind == "request_approval":
            db.add(
                AIApproval(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    action_level=2,
                    action_type=action.get("action_type", "playbook.send"),
                    title=action.get("title", playbook.name),
                    payload_json=json.dumps({"playbook_id": str(playbook.id), "entity_id": entity_id}),
                    status="pending",
                )
            )
            log.append({"type": kind, "ok": True})
        else:
            log.append({"type": kind, "ok": False, "error": "unsupported"})
    run = WorkflowRun(
        tenant_id=tenant_id,
        created_by=actor_id,
        trigger_event=playbook.trigger_event,
        status="completed",
        log_json=json.dumps(log),
        finished_at=datetime.now(UTC),
    )
    db.add(run)
    return run


def create_quote(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    opportunity: Opportunity,
    discount_pct: int,
    tax_pct: int,
    lines: list[dict],
) -> Quote:
    quote = Quote(
        tenant_id=tenant_id,
        created_by=actor_id,
        opportunity_id=opportunity.id,
        status="draft",
        discount_pct=max(0, min(100, discount_pct)),
        tax_pct=max(0, min(100, tax_pct)),
    )
    db.add(quote)
    db.flush()
    for line in lines:
        product = get_owned(db, Product, tenant_id, line["product_id"])
        quantity = max(1, int(line.get("quantity") or 1))
        unit = Decimal(str(line.get("unit_price") if line.get("unit_price") is not None else product.list_price))
        db.add(
            QuoteLine(
                tenant_id=tenant_id,
                created_by=actor_id,
                quote_id=quote.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=unit,
                line_total=(unit * quantity).quantize(Decimal("0.01")),
            )
        )
    db.flush()
    recompute_quote(db, quote)
    if quote.approval_required:
        db.add(
            AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="quote.discount",
                title=f"Approve {quote.discount_pct}% discount on quote",
                payload_json=json.dumps({"quote_id": str(quote.id), "total": str(quote.total)}),
                status="pending",
            )
        )
    return quote


def record_conversation(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    payload: dict,
) -> Conversation:
    contact = None
    if payload.get("contact_id"):
        contact = get_owned(db, Contact, tenant_id, payload["contact_id"])
        if contact.opt_out:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Contact has opted out")
    if not payload.get("consent"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Consent is required to store a conversation")
    row = Conversation(
        tenant_id=tenant_id,
        created_by=actor_id,
        channel=payload.get("channel") or "chat",
        account_id=payload.get("account_id"),
        contact_id=payload.get("contact_id"),
        subject=payload.get("subject") or "",
        status="open",
        outcome=payload.get("outcome") or "",
        sentiment=payload.get("sentiment") or "neutral",
        consent=True,
        provider="mock-voice" if payload.get("channel") == "voice" else "human",
        is_mock=payload.get("channel") == "voice",
        transcript=payload.get("transcript") or "",
        summary=payload.get("summary") or "",
    )
    db.add(row)
    return row


def lifecycle_pulse(db: Session, tenant_id: UUID) -> dict:
    campaigns = db.scalar(select(func.count()).where(Campaign.tenant_id == tenant_id, Campaign.deleted_at.is_(None))) or 0
    sequences = db.scalar(select(func.count()).where(Sequence.tenant_id == tenant_id, Sequence.deleted_at.is_(None))) or 0
    enrollments = db.scalar(select(func.count()).where(SequenceEnrollment.tenant_id == tenant_id, SequenceEnrollment.status == "active")) or 0
    conversations = db.scalar(select(func.count()).where(Conversation.tenant_id == tenant_id, Conversation.deleted_at.is_(None))) or 0
    meetings = db.scalar(select(func.count()).where(MeetingRecord.tenant_id == tenant_id, MeetingRecord.deleted_at.is_(None))) or 0
    quotes = db.scalar(select(func.count()).where(Quote.tenant_id == tenant_id, Quote.deleted_at.is_(None), Quote.status == "draft")) or 0
    at_risk = db.scalar(select(func.count()).where(DealInsight.tenant_id == tenant_id, DealInsight.deleted_at.is_(None), DealInsight.risk_score >= 40)) or 0
    health_risk = db.scalar(select(func.count()).where(HealthScore.tenant_id == tenant_id, HealthScore.deleted_at.is_(None), HealthScore.total < 50)) or 0
    whitespace = db.scalar(select(func.count()).where(WhitespaceCell.tenant_id == tenant_id, WhitespaceCell.deleted_at.is_(None))) or 0
    advocacy = db.scalar(select(func.count()).where(AdvocacyAsset.tenant_id == tenant_id, AdvocacyAsset.deleted_at.is_(None))) or 0
    runs = db.scalar(select(func.count()).where(WorkflowRun.tenant_id == tenant_id, WorkflowRun.deleted_at.is_(None))) or 0
    renew = renewal_metrics(db, tenant_id)
    return {
        "campaigns": int(campaigns),
        "sequences": int(sequences),
        "enrollments": int(enrollments),
        "conversations": int(conversations),
        "meetings": int(meetings),
        "open_quotes": int(quotes),
        "at_risk_deals": int(at_risk),
        "customers": renew["customers"],
        "at_risk_health": int(health_risk),
        "renewals_due_90": renew["due_90"],
        "whitespace": int(whitespace),
        "advocacy": int(advocacy),
        "playbook_runs": int(runs),
        "arr": renew["arr"],
        "note": "SQL counts only. Empty stays empty.",
    }


def fill_whitespace(db: Session, *, tenant_id: UUID, actor_id: UUID, account: Account, products: list) -> list[WhitespaceCell]:
    created = []
    for product in products:
        existing = db.scalar(
            select(WhitespaceCell).where(
                WhitespaceCell.tenant_id == tenant_id,
                WhitespaceCell.account_id == account.id,
                WhitespaceCell.product_id == product.id,
            )
        )
        if existing:
            created.append(existing)
            continue
        propensity = 35 + (15 if account.industry in {"bfsi", "technology", "healthcare"} else 0)
        cell = WhitespaceCell(
            tenant_id=tenant_id,
            created_by=actor_id,
            account_id=account.id,
            product_id=product.id,
            status="no_penetration",
            propensity=clamp(propensity),
            value_hint=product.list_price,
        )
        db.add(cell)
        created.append(cell)
    return created


def renewal_metrics(db: Session, tenant_id: UUID) -> dict:
    rows = db.scalars(select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.deleted_at.is_(None))).all()
    customers = db.scalars(select(Customer).where(Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None))).all()
    arr = sum((row.arr or Decimal("0")) for row in customers)
    due_90 = sum(1 for row in rows if row.renewal_date and date.today() <= row.renewal_date <= date.today() + timedelta(days=90))
    return {
        "renewals": len(rows),
        "customers": len(customers),
        "arr": str(arr),
        "due_90": due_90,
        "grr": 1.0 if customers else 0.0,
        "nrr": 1.0 if customers else 0.0,
        "note": "GRR/NRR stay 1.0 until amendments exist. No invented contraction.",
    }
