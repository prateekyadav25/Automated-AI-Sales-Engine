"""Purchase onboarding, observed health, and reviewable retention tasks.

The work hangs off the onboarding plan opened at close-won. It does not
send, collect, provision, renew, cancel, or calculate a score from missing data.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crm import Contact, Renewal, Task
from app.models.identity import User
from app.models.lifecycle import (
    DealPurchase,
    OnboardingCompletion,
    OnboardingMilestone,
    OnboardingPlan,
    PurchaseHealthSignal,
    Quote,
    QuoteAcceptance,
)
from app.services.audit import emit_event, write_audit
from app.services.crm import add_activity
from app.services.demo_guard import EXPIRED_BLOCK, PREPARED_BLOCK, scope_for_execution
from app.services.provider_ops import begin_action, confirm_action
from app.services.rbac import user_permissions

DONE = {"reviewed", "waived", "completed"}
RECURRING_CADENCE = {"monthly", "quarterly", "annual", "yearly"}
RECURRING_KIND = {"subscription", "recurring"}
SIGNAL_TASKS = {
    "onboarding_followup": (
        "Onboarding follow-up",
        "Review the open onboarding blocker. Do not contact the customer from this task.",
    ),
    "service_issue": (
        "Service issue review",
        "Review the recorded service issue. Do not provision, cancel, or change the purchase.",
    ),
    "check_in": (
        "Customer check-in proposal",
        "Proposal only. No message was sent. A customer relationship is not marketing consent.",
    ),
}
PURCHASE_EVENTS = frozenset(
    {"commercial.onboarding_opened", "purchase.health_recorded", "purchase.onboarding_completed"}
)
_LIMITATIONS = (
    "Missing usage is not zero usage.",
    "No payment integration is connected. That is not an unpaid invoice.",
    "No recent enquiry is not churn.",
    "Overdue onboarding is a service blocker, not cancellation.",
)


class FollowthroughError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def commercial_provenance(db: Session, *, tenant_id: UUID, customer_id: UUID) -> str:
    rows = db.scalars(
        select(DealPurchase).where(
            DealPurchase.tenant_id == tenant_id,
            DealPurchase.customer_id == customer_id,
            DealPurchase.deleted_at.is_(None),
        )
    ).all()
    if not rows:
        return "not_recorded"
    if any(not row.fixture for row in rows):
        return "operator_recorded"
    return "fixture"


def bind_purchase_onboarding(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    purchase: DealPurchase,
    quote: Quote,
    contact: Contact | None,
) -> OnboardingPlan | None:
    if purchase.onboarding_plan_id is None:
        return None
    plan = db.get(OnboardingPlan, purchase.onboarding_plan_id)
    if plan is None or plan.tenant_id != tenant_id or plan.deleted_at is not None:
        return None
    owner_id = None
    if purchase.task_id is not None:
        task = db.get(Task, purchase.task_id)
        if task is not None and task.tenant_id == tenant_id:
            owner_id = task.owner_id
    ensure_purchase_checklist(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        purchase=purchase,
        plan=plan,
        quote=quote,
        contact=contact,
        owner_id=owner_id,
    )
    if plan.status not in {"cancelled", "reversed"}:
        review_retention(db, tenant_id=tenant_id, actor_id=actor_id, purchase=purchase, plan=plan, quote=quote)
    return plan


def ensure_purchase_checklist(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    purchase: DealPurchase,
    plan: OnboardingPlan,
    quote: Quote,
    contact: Contact | None,
    owner_id: UUID | None,
) -> list[OnboardingMilestone]:
    if plan.purchase_id is None:
        plan.purchase_id = purchase.id
    provenance = "fixture" if quote.fixture or purchase.fixture else "operator"
    kind = _product_kind(purchase)
    email = (contact.email or "").strip() if contact is not None else ""
    dates_ready = quote.service_start is not None and quote.service_end is not None
    cadence = (quote.billing_cadence or "").strip()
    copied = "Copied from the accepted quote. Not provider-verified."
    specs = [
        {
            "key": "information.billing",
            "step": "information",
            "title": "Billing contact email",
            "required": True,
            "status": "reviewed" if email else "requested",
            "review_state": "reviewed" if email else "",
            "evidence": copied if email else "",
            "next_action": "Billing contact is recorded on the quote." if email else "Record the billing contact email.",
            "due_date": None,
            "proof": "billing email",
        },
        {
            "key": "information.service_dates",
            "step": "information",
            "title": "Service dates",
            "required": True,
            "status": "reviewed" if dates_ready else "requested",
            "review_state": "reviewed" if dates_ready else "",
            "evidence": copied if dates_ready else "",
            "next_action": "Service dates are recorded on the quote." if dates_ready else "Record the agreed service start and end.",
            "due_date": quote.service_end if dates_ready else None,
            "proof": "service dates",
        },
        {
            "key": "information.cadence",
            "step": "information",
            "title": "Billing cadence",
            "required": True,
            "status": "reviewed" if cadence else "requested",
            "review_state": "reviewed" if cadence else "",
            "evidence": _cadence_evidence(cadence, kind) if cadence else "",
            "next_action": "Billing cadence is recorded. It does not renew the purchase." if cadence else "Record the billing cadence.",
            "due_date": None,
            "proof": "billing cadence",
        },
        {
            "key": "setup.access",
            "step": "setup",
            "title": "Product setup",
            "required": True,
            "status": "pending",
            "review_state": "",
            "evidence": "",
            "next_action": "Product setup is pending. This step does not provision a service.",
            "due_date": None,
            "proof": "setup evidence",
        },
        {
            "key": "delivery.verify",
            "step": "delivery",
            "title": "Delivery verification",
            "required": True,
            "status": "pending",
            "review_state": "",
            "evidence": "",
            "next_action": "Delivery stays unverified until evidence is reviewed. A due date does not prove delivery.",
            "due_date": None,
            "proof": "delivery evidence",
        },
        {
            "key": "completion.gate",
            "step": "completion",
            "title": "Onboarding completion",
            "required": True,
            "status": "blocked",
            "review_state": "",
            "evidence": "",
            "next_action": "Complete onboarding only after required steps are reviewed or waived.",
            "due_date": None,
            "proof": "completion decision",
        },
        {
            "key": "notes.optional",
            "step": "notes",
            "title": "Additional customer notes",
            "required": False,
            "status": "pending",
            "review_state": "",
            "evidence": "",
            "next_action": "Optional. This does not block completion.",
            "due_date": None,
            "proof": "optional note",
        },
    ]
    existing = {
        row.template_key: row
        for row in db.scalars(
            select(OnboardingMilestone).where(
                OnboardingMilestone.plan_id == plan.id,
                OnboardingMilestone.deleted_at.is_(None),
            )
        ).all()
    }
    created: list[OnboardingMilestone] = []
    for position, spec in enumerate(specs, start=1):
        row = existing.get(spec["key"])
        if row is None:
            row = OnboardingMilestone(
                tenant_id=tenant_id,
                created_by=actor_id,
                plan_id=plan.id,
                purchase_id=purchase.id,
                title=spec["title"],
                step=spec["step"],
                required=spec["required"],
                status=spec["status"],
                review_state=spec["review_state"],
                evidence=spec["evidence"],
                next_action=spec["next_action"],
                due_date=spec["due_date"],
                owner_id=owner_id,
                position=position,
                sla_days=0,
                required_evidence=spec["proof"],
                provenance=provenance if spec["evidence"] else "",
                template_key=spec["key"],
            )
            db.add(row)
            created.append(row)
        existing[spec["key"]] = row
    db.flush()
    links = {
        "setup.access": "information.cadence",
        "delivery.verify": "setup.access",
        "completion.gate": "delivery.verify",
    }
    for key, parent_key in links.items():
        row = existing.get(key)
        parent = existing.get(parent_key)
        if row is not None and parent is not None and row.depends_on_id is None:
            row.depends_on_id = parent.id
    keys = {spec["key"] for spec in specs}
    items = sorted(
        (row for row in existing.values() if row.template_key in keys),
        key=lambda row: (row.position or 0, row.template_key),
    )
    _refresh_plan(plan, items)
    return items


def record_item_evidence(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    plan_id: UUID,
    item_id: UUID,
    note: str,
    source: str,
) -> dict:
    _require_write(db, tenant_id, actor_id)
    plan, item = _item(db, tenant_id, plan_id, item_id)
    _plan_is_open(plan)
    cleaned = note.strip()
    if not cleaned:
        raise FollowthroughError("Evidence needs a note. An empty upload is not proof.")
    if source not in {"operator", "fixture", "document", "model"}:
        raise FollowthroughError("Evidence source is not recognized.")
    provenance = "fixture" if source == "fixture" else "operator"
    item.evidence = f"{item.evidence}\n{cleaned}".strip()
    item.status = "supplied"
    item.review_state = "needs_review"
    item.provenance = provenance
    item.next_action = "Evidence is supplied and still needs review. It is not provider-verified."
    _refresh_plan(plan, _items(db, plan.id))
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="onboarding.evidence_recorded",
        entity_type="onboarding_milestone",
        entity_id=str(item.id),
        after={"source": source, "review_state": "needs_review", "provider_verified": False},
    )
    return purchase_view(db, tenant_id=tenant_id, purchase_id=plan.purchase_id)


def review_item(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    plan_id: UUID,
    item_id: UUID,
    note: str = "",
) -> dict:
    _require_write(db, tenant_id, actor_id)
    plan, item = _item(db, tenant_id, plan_id, item_id)
    _plan_is_open(plan)
    if item.template_key == "completion.gate":
        raise FollowthroughError("Use the completion decision for this step.")
    if item.status == "waived":
        raise FollowthroughError("This step is waived. The waiver stays on the record.")
    if not (item.evidence or "").strip():
        raise FollowthroughError("Evidence is required before this step can be reviewed.")
    if note.strip():
        item.evidence = f"{item.evidence}\nReview: {note.strip()}".strip()
    item.status = "reviewed"
    item.review_state = "reviewed"
    item.completed_by = actor_id
    item.completed_at = datetime.now(UTC)
    item.next_action = "Reviewed by an operator. Not provider-verified."
    _refresh_plan(plan, _items(db, plan.id))
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="onboarding.item_reviewed",
        entity_type="onboarding_milestone",
        entity_id=str(item.id),
        after={"provider_verified": False},
    )
    return purchase_view(db, tenant_id=tenant_id, purchase_id=plan.purchase_id)


def waive_item(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    plan_id: UUID,
    item_id: UUID,
    reason: str,
) -> dict:
    _require_write(db, tenant_id, actor_id)
    plan, item = _item(db, tenant_id, plan_id, item_id)
    _plan_is_open(plan)
    if not reason.strip():
        raise FollowthroughError("A waiver needs a reason.")
    if not item.required:
        raise FollowthroughError("An optional step does not need a waiver.")
    if item.template_key == "completion.gate":
        raise FollowthroughError("The completion decision cannot be waived.")
    item.status = "waived"
    item.review_state = "waived"
    item.waiver_reason = reason.strip()
    item.completed_by = actor_id
    item.completed_at = datetime.now(UTC)
    item.next_action = "Waived. Payment, signature, provisioning, and delivery stay unrecorded."
    _refresh_plan(plan, _items(db, plan.id))
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="onboarding.item_waived",
        entity_type="onboarding_milestone",
        entity_id=str(item.id),
        after={"reason": reason.strip()},
    )
    return purchase_view(db, tenant_id=tenant_id, purchase_id=plan.purchase_id)


def complete_onboarding(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    plan_id: UUID,
    evidence: str,
) -> dict:
    _require_write(db, tenant_id, actor_id)
    plan = _plan(db, tenant_id, plan_id)
    if plan.purchase_id is None:
        raise FollowthroughError("This onboarding plan is not bound to a purchase.")
    if plan.status == "completed":
        return purchase_view(db, tenant_id=tenant_id, purchase_id=plan.purchase_id)
    _plan_is_open(plan)
    if not evidence.strip():
        raise FollowthroughError("Completion needs evidence.")
    items = _items(db, plan.id)
    open_items = [row for row in items if row.required and row.template_key != "completion.gate" and row.status not in DONE]
    if open_items:
        raise FollowthroughError("Required onboarding steps are still open.")
    gate = next((row for row in items if row.template_key == "completion.gate"), None)
    moment = datetime.now(UTC)
    if gate is not None:
        gate.status = "completed"
        gate.review_state = "reviewed"
        gate.evidence = evidence.strip()
        gate.completed_by = actor_id
        gate.completed_at = moment
        gate.provenance = gate.provenance or "operator"
        gate.next_action = "Onboarding is complete for this purchase. Payment, contract, provisioning, first value, and renewal are separate."
    waived = [row.template_key for row in items if row.status == "waived"]
    plan.status = "completed"
    plan.completed_by = actor_id
    plan.completed_at = moment
    plan.completion_evidence = evidence.strip()
    plan.blocker = ""
    plan.next_action = "Onboarding is complete for this purchase."
    db.add(
        OnboardingCompletion(
            tenant_id=tenant_id,
            created_by=actor_id,
            plan_id=plan.id,
            purchase_id=plan.purchase_id,
            customer_id=plan.customer_id,
            action="completed",
            evidence=evidence.strip(),
            waived_json=json.dumps(waived),
            recorded_at=moment,
        )
    )
    db.flush()
    purchase = db.get(DealPurchase, plan.purchase_id)
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="purchase.onboarding_completed",
        entity_type="onboarding_plan",
        entity_id=str(plan.id),
        after={
            "purchase_id": str(plan.purchase_id),
            "waived": waived,
            "payment_recorded": False,
            "activated": False,
        },
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="purchase.onboarding_completed",
        entity_type="onboarding_plan",
        entity_id=str(plan.id),
        payload={"purchase_id": str(plan.purchase_id), "plan_id": str(plan.id)},
    )
    if purchase is not None:
        add_activity(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="customer",
            entity_id=str(plan.customer_id),
            activity_type="onboarding_completed",
            title="Onboarding completed",
            body="The purchased onboarding was completed. Payment, contract, provisioning, first value, and renewal were not recorded.",
        )
    return purchase_view(db, tenant_id=tenant_id, purchase_id=plan.purchase_id)


def correct_onboarding(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    plan_id: UUID,
    reason: str,
) -> dict:
    _require_write(db, tenant_id, actor_id)
    plan = _plan(db, tenant_id, plan_id)
    if plan.purchase_id is None:
        raise FollowthroughError("This onboarding plan is not bound to a purchase.")
    if not reason.strip():
        raise FollowthroughError("A correction needs a reason.")
    if plan.status != "completed":
        raise FollowthroughError("Only a completed onboarding record can be corrected.")
    gate = next((row for row in _items(db, plan.id) if row.template_key == "completion.gate"), None)
    if gate is not None and gate.status == "completed":
        gate.status = "ready"
        gate.review_state = ""
        gate.next_action = "Corrected. Complete this purchase again only with a new authorized decision."
    moment = datetime.now(UTC)
    db.add(
        OnboardingCompletion(
            tenant_id=tenant_id,
            created_by=actor_id,
            plan_id=plan.id,
            purchase_id=plan.purchase_id,
            customer_id=plan.customer_id,
            action="corrected",
            evidence=reason.strip(),
            waived_json="[]",
            recorded_at=moment,
        )
    )
    db.flush()
    plan.status = "open"
    plan.completed_at = None
    plan.completed_by = None
    _refresh_plan(plan, _items(db, plan.id))
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="purchase.onboarding_corrected",
        entity_type="onboarding_plan",
        entity_id=str(plan.id),
        after={"reason": reason.strip()},
    )
    return purchase_view(db, tenant_id=tenant_id, purchase_id=plan.purchase_id)


def record_health_signal(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    purchase_id: UUID,
    signal_type: str,
    definition: str = "",
    source: str = "operator",
    provenance: str = "operator",
    value_text: str = "",
    value_numeric: Decimal | None = None,
    period_key: str = "",
    freshness: str = "fresh",
    coverage: str = "insufficient",
    evidence: str = "",
    limitations: str = "",
) -> dict:
    _require_write(db, tenant_id, actor_id)
    purchase = _purchase(db, tenant_id, purchase_id)
    period = period_key.strip()
    if not period:
        raise FollowthroughError("A period is required so a later signal stays distinct.")
    kind = signal_type.strip()[:40]
    if not kind:
        raise FollowthroughError("A signal type is required.")
    if freshness not in {"fresh", "stale", "missing", "unsupported"}:
        raise FollowthroughError("Freshness must be fresh, stale, missing, or unsupported.")
    if coverage not in {"sufficient", "insufficient"}:
        raise FollowthroughError("Coverage must be sufficient or insufficient.")
    numeric = value_numeric
    text = value_text.strip()
    note = limitations.strip()
    stored_provenance = provenance if provenance in {"operator", "fixture", "provider", "unsupported"} else "operator"
    if freshness in {"missing", "unsupported"} or stored_provenance == "unsupported":
        numeric = None
        if freshness == "missing":
            text = ""
            note = f"{note} Missing usage is not zero usage.".strip()
    if kind in {"payment", "invoice"} and stored_provenance in {"provider", "unsupported"}:
        stored_provenance = "unsupported"
        freshness = "unsupported"
        coverage = "insufficient"
        numeric = None
        text = ""
        note = f"{note} Payment integration is unsupported. This is not an unpaid invoice.".strip()
    if purchase.fixture and stored_provenance == "operator":
        stored_provenance = "fixture"
    existing = db.scalar(
        select(PurchaseHealthSignal).where(
            PurchaseHealthSignal.tenant_id == tenant_id,
            PurchaseHealthSignal.purchase_id == purchase.id,
            PurchaseHealthSignal.signal_type == kind,
            PurchaseHealthSignal.period_key == period,
            PurchaseHealthSignal.deleted_at.is_(None),
        )
    )
    if existing is None:
        existing = PurchaseHealthSignal(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=purchase.customer_id,
            purchase_id=purchase.id,
            signal_type=kind,
            definition=definition.strip() or _definition(kind),
            source=source[:40] or "operator",
            provenance=stored_provenance,
            observed_at=datetime.now(UTC),
            period_key=period,
            value_text=text,
            value_numeric=numeric,
            freshness=freshness,
            coverage=coverage,
            evidence=evidence.strip(),
            limitations=note,
            inferred_risk="",
            fixture=purchase.fixture,
        )
        try:
            with db.begin_nested():
                db.add(existing)
                db.flush()
        except IntegrityError:
            existing = db.scalar(
                select(PurchaseHealthSignal).where(
                    PurchaseHealthSignal.tenant_id == tenant_id,
                    PurchaseHealthSignal.purchase_id == purchase.id,
                    PurchaseHealthSignal.signal_type == kind,
                    PurchaseHealthSignal.period_key == period,
                    PurchaseHealthSignal.deleted_at.is_(None),
                )
            )
    plan = db.get(OnboardingPlan, purchase.onboarding_plan_id) if purchase.onboarding_plan_id else None
    quote = db.get(Quote, purchase.quote_id)
    if plan is not None and quote is not None and plan.status not in {"cancelled", "reversed"}:
        review_retention(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            purchase=purchase,
            plan=plan,
            quote=quote,
            signal_type=kind,
            period_key=period,
        )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="purchase.health_recorded",
        entity_type="deal_purchase",
        entity_id=str(purchase.id),
        payload={"purchase_id": str(purchase.id), "plan_id": str(plan.id) if plan else "", "signal_type": kind, "period_key": period},
    )
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="purchase.health_recorded",
        entity_type="deal_purchase",
        entity_id=str(purchase.id),
        after={"signal_type": kind, "period_key": period, "freshness": freshness, "coverage": coverage, "score": None},
    )
    return purchase_view(db, tenant_id=tenant_id, purchase_id=purchase.id)


def explain_health(db: Session, *, tenant_id: UUID, customer_id: UUID, purchase_id: UUID | None = None) -> dict:
    stmt = select(PurchaseHealthSignal).where(
        PurchaseHealthSignal.tenant_id == tenant_id,
        PurchaseHealthSignal.customer_id == customer_id,
        PurchaseHealthSignal.deleted_at.is_(None),
    )
    if purchase_id is not None:
        stmt = stmt.where(PurchaseHealthSignal.purchase_id == purchase_id)
    signals = list(db.scalars(stmt.order_by(PurchaseHealthSignal.observed_at.asc())).all())
    limitations = list(_LIMITATIONS)
    for row in signals:
        if row.limitations and row.limitations not in limitations:
            limitations.append(row.limitations)
    if not signals:
        return {
            "status": "insufficient_evidence",
            "score": None,
            "coverage": "insufficient",
            "limitations": limitations,
            "signals": [],
        }
    observed = all(row.freshness == "fresh" and row.coverage == "sufficient" and _has_value(row) for row in signals)
    return {
        "status": "observed" if observed else "insufficient_evidence",
        "score": None,
        "coverage": "sufficient" if observed else "insufficient",
        "limitations": limitations,
        "signals": [_signal_payload(row) for row in signals],
    }


def review_retention(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    purchase: DealPurchase,
    plan: OnboardingPlan,
    quote: Quote,
    signal_type: str = "",
    period_key: str = "",
) -> Task | None:
    if plan.status in {"cancelled", "reversed"} or purchase.status != "won":
        return None
    created: Task | None = None
    kind = signal_type.strip()
    if kind in SIGNAL_TASKS and not (kind == "onboarding_followup" and plan.status == "completed"):
        title, advice = SIGNAL_TASKS[kind]
        period = period_key.strip() or "unspecified"
        created = _task_once(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            purchase=purchase,
            owner_id=_owner(db, plan),
            title=f"{title} {period}",
            description=_task_body(purchase, kind, period, advice, plan.blocker),
            key=f"retention:{purchase.id}:{kind}:{period}",
        )
    renewable, term_end = _renewable(purchase, quote)
    if renewable and term_end:
        renewal_task = _task_once(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            purchase=purchase,
            owner_id=_owner(db, plan),
            title=f"Renewal preparation {term_end}",
            description=(
                f"Purchase {purchase.id}. Recorded term ends {term_end}. "
                "Prepare the renewal review. This task does not renew, charge, discount, or contact the customer."
            ),
            key=f"retention:{purchase.id}:renewal_prep:{term_end}",
        )
        created = created or renewal_task
    return created


def hold_elapsed_items(db: Session, plan: OnboardingPlan) -> int:
    today = date.today()
    elapsed = 0
    for row in _items(db, plan.id):
        if row.due_date is not None and row.due_date < today and row.status not in DONE:
            elapsed += 1
    return elapsed


def reconcile_purchase_event(db: Session, event, *, actor_id: UUID | None = None) -> str:
    if event.event_type not in PURCHASE_EVENTS:
        return "ignored"
    try:
        payload = json.loads(event.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    purchase = _purchase_from_payload(db, event.tenant_id, payload)
    if purchase is None or purchase.status != "won":
        return "missing_purchase"
    plan = db.get(OnboardingPlan, purchase.onboarding_plan_id) if purchase.onboarding_plan_id else None
    quote = db.get(Quote, purchase.quote_id)
    if plan is None or quote is None or plan.tenant_id != event.tenant_id or quote.tenant_id != event.tenant_id:
        return "missing_plan"
    if plan.status in {"cancelled", "reversed"}:
        return "closed"
    acceptance = db.scalar(
        select(QuoteAcceptance).where(
            QuoteAcceptance.tenant_id == event.tenant_id,
            QuoteAcceptance.quote_id == quote.id,
            QuoteAcceptance.deleted_at.is_(None),
        )
    )
    contact = db.get(Contact, acceptance.contact_id) if acceptance is not None and acceptance.contact_id else None
    if contact is not None and contact.tenant_id != event.tenant_id:
        contact = None
    ensure_purchase_checklist(
        db,
        tenant_id=event.tenant_id,
        actor_id=actor_id,
        purchase=purchase,
        plan=plan,
        quote=quote,
        contact=contact,
        owner_id=_owner(db, plan),
    )
    hold_elapsed_items(db, plan)
    if plan.status == "completed" and event.event_type != "purchase.health_recorded":
        return "preserved"
    review_retention(
        db,
        tenant_id=event.tenant_id,
        actor_id=actor_id,
        purchase=purchase,
        plan=plan,
        quote=quote,
        signal_type=str(payload.get("signal_type") or "") if event.event_type == "purchase.health_recorded" else "",
        period_key=str(payload.get("period_key") or ""),
    )
    return "reconciled"


def customer_followthrough(db: Session, *, tenant_id: UUID, customer_id: UUID) -> dict:
    plans = db.scalars(
        select(OnboardingPlan)
        .where(OnboardingPlan.tenant_id == tenant_id, OnboardingPlan.customer_id == customer_id, OnboardingPlan.deleted_at.is_(None))
        .order_by(OnboardingPlan.created_at.asc())
    ).all()
    milestones: list[dict] = []
    for plan in plans:
        milestones.extend(item_payload(db, tenant_id, row) for row in _items(db, plan.id))
    purchases = db.scalars(
        select(DealPurchase).where(
            DealPurchase.tenant_id == tenant_id,
            DealPurchase.customer_id == customer_id,
            DealPurchase.deleted_at.is_(None),
        )
    ).all()
    tasks: list[dict] = []
    for purchase in purchases:
        tasks.extend(_retention_tasks(db, tenant_id, purchase.id))
    status = ""
    if any(plan.status == "open" for plan in plans):
        status = "open"
    elif plans:
        status = plans[-1].status
    return {
        "commercial_provenance": commercial_provenance(db, tenant_id=tenant_id, customer_id=customer_id),
        "onboarding_status": status,
        "milestones": milestones,
        "purchase_health": [_signal_payload(row) for row in _signals(db, tenant_id, customer_id)],
        "health_explanation": explain_health(db, tenant_id=tenant_id, customer_id=customer_id),
        "retention_tasks": tasks,
        "completions": [_completion_payload(db, tenant_id, row) for row in _completions(db, tenant_id, customer_id)],
    }


def purchase_view(db: Session, *, tenant_id: UUID, purchase_id: UUID | None) -> dict:
    if purchase_id is None:
        raise FollowthroughError("Not found", 404)
    purchase = _purchase(db, tenant_id, purchase_id)
    plan = db.get(OnboardingPlan, purchase.onboarding_plan_id) if purchase.onboarding_plan_id else None
    quote = db.get(Quote, purchase.quote_id)
    renewable, term_end = _renewable(purchase, quote) if quote is not None else (False, "")
    renewal = db.scalar(
        select(Renewal).where(
            Renewal.tenant_id == tenant_id,
            Renewal.customer_id == purchase.customer_id,
            Renewal.deleted_at.is_(None),
        )
    )
    return {
        "purchase_id": purchase.id,
        "customer_id": purchase.customer_id,
        "plan_id": plan.id if plan else None,
        "onboarding_status": plan.status if plan else "",
        "checklist": [item_payload(db, tenant_id, row) for row in _items(db, plan.id)] if plan else [],
        "completions": [
            _completion_payload(db, tenant_id, row)
            for row in _completions(db, tenant_id, purchase.customer_id)
            if row.purchase_id == purchase.id
        ],
        "health": explain_health(db, tenant_id=tenant_id, customer_id=purchase.customer_id, purchase_id=purchase.id),
        "retention_tasks": _retention_tasks(db, tenant_id, purchase.id),
        "renewal_recorded": bool(renewal and renewal.renewal_date),
        "renewal_note": _renewal_note(renewable, term_end, bool(renewal and renewal.renewal_date)),
        "payment_status": purchase.payment_status,
        "external_released": False,
        "external_block": _external_note(db, tenant_id),
        "product_kind": _product_kind(purchase),
        "provenance": "fixture" if purchase.fixture else "operator_recorded",
    }


def checklist_for_plan(db: Session, *, tenant_id: UUID, plan: OnboardingPlan | None) -> list[dict]:
    if plan is None or plan.tenant_id != tenant_id:
        return []
    return [item_payload(db, tenant_id, row) for row in _items(db, plan.id)]


def item_payload(db: Session, tenant_id: UUID, item: OnboardingMilestone) -> dict:
    owner_name = ""
    if item.owner_id is not None:
        owner = db.get(User, item.owner_id)
        if owner is not None and owner.tenant_id == tenant_id:
            owner_name = owner.name or ""
    return {
        "id": str(item.id),
        "plan_id": str(item.plan_id),
        "purchase_id": str(item.purchase_id) if item.purchase_id else "",
        "template_key": item.template_key,
        "step": item.step,
        "title": item.title,
        "status": item.status,
        "required": bool(item.required),
        "owner_name": owner_name,
        "depends_on_id": str(item.depends_on_id) if item.depends_on_id else "",
        "next_action": item.next_action,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "evidence": item.evidence,
        "review_state": item.review_state,
        "waiver_reason": item.waiver_reason,
        "provenance": item.provenance,
    }


def _require_write(db: Session, tenant_id: UUID, actor_id: UUID) -> None:
    actor = db.get(User, actor_id)
    if actor is None or not actor.is_active or actor.tenant_id != tenant_id:
        raise FollowthroughError("Permission denied.", 403)
    if "success.write" not in user_permissions(db, actor):
        raise FollowthroughError("Permission denied.", 403)


def _plan(db: Session, tenant_id: UUID, plan_id: UUID) -> OnboardingPlan:
    row = db.scalar(
        select(OnboardingPlan).where(
            OnboardingPlan.id == plan_id,
            OnboardingPlan.tenant_id == tenant_id,
            OnboardingPlan.deleted_at.is_(None),
        )
    )
    if row is None:
        raise FollowthroughError("Not found", 404)
    return row


def _purchase(db: Session, tenant_id: UUID, purchase_id: UUID) -> DealPurchase:
    row = db.scalar(
        select(DealPurchase).where(
            DealPurchase.id == purchase_id,
            DealPurchase.tenant_id == tenant_id,
            DealPurchase.deleted_at.is_(None),
        )
    )
    if row is None:
        raise FollowthroughError("Not found", 404)
    return row


def _item(db: Session, tenant_id: UUID, plan_id: UUID, item_id: UUID) -> tuple[OnboardingPlan, OnboardingMilestone]:
    plan = _plan(db, tenant_id, plan_id)
    item = db.scalar(
        select(OnboardingMilestone).where(
            OnboardingMilestone.id == item_id,
            OnboardingMilestone.plan_id == plan.id,
            OnboardingMilestone.tenant_id == tenant_id,
            OnboardingMilestone.deleted_at.is_(None),
        )
    )
    if item is None:
        raise FollowthroughError("Not found", 404)
    return plan, item


def _plan_is_open(plan: OnboardingPlan) -> None:
    if plan.status in {"completed", "cancelled", "reversed"}:
        raise FollowthroughError("Completed or cancelled onboarding stays closed until an authorized correction.")


def _items(db: Session, plan_id: UUID) -> list[OnboardingMilestone]:
    return list(
        db.scalars(
            select(OnboardingMilestone)
            .where(OnboardingMilestone.plan_id == plan_id, OnboardingMilestone.deleted_at.is_(None))
            .order_by(OnboardingMilestone.position.asc())
        ).all()
    )


def _refresh_plan(plan: OnboardingPlan, items: list[OnboardingMilestone]) -> None:
    if plan.status == "completed":
        return
    required_info = [row for row in items if row.required and row.step == "information" and row.status not in DONE]
    setup = next((row for row in items if row.template_key == "setup.access"), None)
    if setup is not None and setup.status not in DONE | {"supplied"}:
        setup.status = "blocked" if required_info else "pending"
    gate = next((row for row in items if row.template_key == "completion.gate"), None)
    others_done = all(row.status in DONE for row in items if row.required and row.template_key != "completion.gate")
    if gate is not None and gate.status not in DONE:
        gate.status = "ready" if others_done else "blocked"
        gate.next_action = (
            "Onboarding can be completed by an authorized reviewer. Payment, contract, provisioning, and first value stay separate."
            if others_done
            else "Complete onboarding only after required steps are reviewed or waived."
        )
    open_required = [row for row in items if row.required and row.status not in DONE and row.template_key != "completion.gate"]
    if open_required:
        plan.blocker = open_required[0].title
        plan.next_action = open_required[0].next_action
    elif gate is not None and gate.status == "ready":
        plan.blocker = ""
        plan.next_action = gate.next_action
    else:
        plan.blocker = ""


def _product_kind(purchase: DealPurchase) -> str:
    try:
        body = json.loads(purchase.snapshot_json or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(body, dict):
        return ""
    return str(body.get("product_kind") or "")


def _snapshot_lines(purchase: DealPurchase) -> list[dict]:
    try:
        body = json.loads(purchase.snapshot_json or "{}")
    except json.JSONDecodeError:
        return []
    if not isinstance(body, dict):
        return []
    lines = body.get("lines")
    if not isinstance(lines, list):
        return []
    return [row for row in lines if isinstance(row, dict)]


def _renewable(purchase: DealPurchase, quote: Quote) -> tuple[bool, str]:
    try:
        body = json.loads(purchase.snapshot_json or "{}")
    except json.JSONDecodeError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    kinds = [str(row.get("kind") or "").strip().lower() for row in _snapshot_lines(purchase)]
    if not kinds:
        kind = str(body.get("product_kind") or "").strip().lower()
        kinds = [kind] if kind else []
    cadence = str(body.get("billing_cadence") or quote.billing_cadence or "").strip().lower()
    service_end = str(body.get("service_end") or "")
    if not service_end and quote.service_end is not None:
        service_end = quote.service_end.isoformat()
    if not kinds or any(kind not in RECURRING_KIND for kind in kinds):
        return False, ""
    if cadence not in RECURRING_CADENCE:
        return False, ""
    if not service_end:
        return False, ""
    return True, service_end


def _cadence_evidence(cadence: str, kind: str) -> str:
    if kind.strip().lower() in {"", "one_time", "one-time", "mixed"}:
        return f"Cadence {cadence} is recorded. The purchased kind is not a renewable term."
    return f"Cadence {cadence} is recorded. No renewal was created."


def _definition(kind: str) -> str:
    definitions = {
        "usage": "Observed product usage for the purchased scope.",
        "payment": "Payment observation. A missing integration is not an invoice.",
        "invoice": "Invoice observation. Unsupported means no invoice was read.",
        "service_issue": "Operator-recorded service issue for this purchase.",
        "check_in": "Proposed customer check-in. It is not a sent message.",
        "onboarding_followup": "Open onboarding work for this purchase.",
    }
    return definitions.get(kind, "Operator-recorded purchase signal.")


def _has_value(row: PurchaseHealthSignal) -> bool:
    return row.value_numeric is not None or bool(row.value_text.strip())


def _signal_payload(row: PurchaseHealthSignal) -> dict:
    return {
        "id": str(row.id),
        "purchase_id": str(row.purchase_id),
        "signal_type": row.signal_type,
        "definition": row.definition,
        "source": row.source,
        "provenance": row.provenance,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "period_key": row.period_key,
        "value_text": row.value_text,
        "value_numeric": None if row.value_numeric is None else str(row.value_numeric),
        "freshness": row.freshness,
        "coverage": row.coverage,
        "evidence": row.evidence,
        "limitations": row.limitations,
        "inferred_risk": row.inferred_risk,
        "fixture": row.fixture,
    }


def _signals(db: Session, tenant_id: UUID, customer_id: UUID) -> list[PurchaseHealthSignal]:
    return list(
        db.scalars(
            select(PurchaseHealthSignal)
            .where(
                PurchaseHealthSignal.tenant_id == tenant_id,
                PurchaseHealthSignal.customer_id == customer_id,
                PurchaseHealthSignal.deleted_at.is_(None),
            )
            .order_by(PurchaseHealthSignal.observed_at.asc())
        ).all()
    )


def _completions(db: Session, tenant_id: UUID, customer_id: UUID) -> list[OnboardingCompletion]:
    return list(
        db.scalars(
            select(OnboardingCompletion)
            .where(
                OnboardingCompletion.tenant_id == tenant_id,
                OnboardingCompletion.customer_id == customer_id,
                OnboardingCompletion.deleted_at.is_(None),
            )
            .order_by(OnboardingCompletion.recorded_at.asc())
        ).all()
    )


def _completion_payload(db: Session, tenant_id: UUID, row: OnboardingCompletion) -> dict:
    actor = db.get(User, row.created_by) if row.created_by else None
    name = actor.name if actor is not None and actor.tenant_id == tenant_id else ""
    try:
        waived = json.loads(row.waived_json or "[]")
    except json.JSONDecodeError:
        waived = []
    return {
        "id": str(row.id),
        "purchase_id": str(row.purchase_id) if row.purchase_id else "",
        "action": row.action,
        "evidence": row.evidence,
        "waived": waived if isinstance(waived, list) else [],
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        "actor_name": name,
    }


def _owner(db: Session, plan: OnboardingPlan) -> UUID | None:
    row = db.scalar(
        select(OnboardingMilestone).where(
            OnboardingMilestone.plan_id == plan.id,
            OnboardingMilestone.owner_id.is_not(None),
            OnboardingMilestone.deleted_at.is_(None),
        )
    )
    return row.owner_id if row is not None else None


def _task_once(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    purchase: DealPurchase,
    owner_id: UUID | None,
    title: str,
    description: str,
    key: str,
) -> Task | None:
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="purchase.retention",
        idempotency_key=key,
        provider="purchase-record",
        entity_type="purchase",
        entity_id=str(purchase.id),
        request_summary=title[:180],
    )
    if action.external_id:
        existing = db.get(Task, UUID(action.external_id))
        if existing is not None and existing.tenant_id == tenant_id and existing.deleted_at is None:
            return existing
    existing = db.scalar(
        select(Task).where(
            Task.tenant_id == tenant_id,
            Task.entity_type == "purchase",
            Task.entity_id == str(purchase.id),
            Task.title == title[:200],
            Task.deleted_at.is_(None),
        )
    )
    if existing is not None:
        if action.status != "CONFIRMED":
            confirm_action(action, provider="purchase-record", external_id=str(existing.id), response_summary="existing task")
        return existing
    task = Task(
        tenant_id=tenant_id,
        created_by=actor_id,
        title=title[:200],
        description=description,
        status="open",
        priority="medium",
        owner_id=owner_id,
        entity_type="purchase",
        entity_id=str(purchase.id),
        source="retention",
    )
    db.add(task)
    db.flush()
    confirm_action(action, provider="purchase-record", external_id=str(task.id), response_summary="internal task")
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="purchase.retention_opened",
        entity_type="task",
        entity_id=str(task.id),
        after={"purchase_id": str(purchase.id), "external_released": False},
    )
    return task


def _task_body(purchase: DealPurchase, kind: str, period: str, advice: str, blocker: str) -> str:
    return (
        f"Purchase {purchase.id}. Trigger {kind}. Period {period}. "
        f"Recommended action: {advice} Blocker: {blocker or 'none recorded'}. "
        "No message, charge, renewal, or cancellation was created."
    )


def _retention_tasks(db: Session, tenant_id: UUID, purchase_id: UUID) -> list[dict]:
    rows = db.scalars(
        select(Task).where(
            Task.tenant_id == tenant_id,
            Task.entity_type == "purchase",
            Task.entity_id == str(purchase_id),
            Task.source == "retention",
            Task.deleted_at.is_(None),
        )
    ).all()
    payload = []
    for row in rows:
        owner_name = ""
        if row.owner_id is not None:
            owner = db.get(User, row.owner_id)
            if owner is not None and owner.tenant_id == tenant_id:
                owner_name = owner.name or ""
        payload.append(
            {
                "id": str(row.id),
                "title": row.title,
                "status": row.status,
                "description": row.description,
                "owner_name": owner_name,
                "purchase_id": str(purchase_id),
            }
        )
    return payload


def _purchase_from_payload(db: Session, tenant_id: UUID, payload: dict) -> DealPurchase | None:
    raw = str(payload.get("purchase_id") or "")
    if raw:
        try:
            purchase_id = UUID(raw)
        except ValueError:
            return None
        return db.scalar(
            select(DealPurchase).where(
                DealPurchase.id == purchase_id,
                DealPurchase.tenant_id == tenant_id,
                DealPurchase.deleted_at.is_(None),
            )
        )
    raw_plan = str(payload.get("plan_id") or "")
    if not raw_plan:
        return None
    try:
        plan_id = UUID(raw_plan)
    except ValueError:
        return None
    plan = db.scalar(
        select(OnboardingPlan).where(
            OnboardingPlan.id == plan_id,
            OnboardingPlan.tenant_id == tenant_id,
            OnboardingPlan.deleted_at.is_(None),
        )
    )
    if plan is None or plan.purchase_id is None:
        return None
    return db.scalar(
        select(DealPurchase).where(
            DealPurchase.id == plan.purchase_id,
            DealPurchase.tenant_id == tenant_id,
            DealPurchase.deleted_at.is_(None),
        )
    )


def _external_note(db: Session, tenant_id: UUID) -> str:
    scope = scope_for_execution(db, tenant_id)
    if scope is None:
        return ""
    expires = scope.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires is not None and expires <= datetime.now(UTC):
        return EXPIRED_BLOCK
    if scope.status == "prepared":
        return PREPARED_BLOCK
    if scope.status != "authorized":
        return "External work stays blocked."
    return ""


def _renewal_note(renewable: bool, term_end: str, recorded: bool) -> str:
    if recorded:
        return "A renewal date is already recorded. This purchase path did not change it."
    if renewable and term_end:
        return f"A recurring term ends {term_end}. Preparation does not renew or charge."
    return "No renewal date is recorded."
