"""Evidence-backed close-won on the existing quote, customer, and onboarding records.

Acceptance stores evidence. It does not create a customer. Close-won is a
separate operator decision. The decision copies the accepted quote version
and opens one onboarding task. It does not send, collect, provision, or
mark the customer live.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.crm import Account, Contact, Customer, Lead, Opportunity, Task
from app.models.execution import JourneyLink
from app.models.identity import Tenant, User
from app.models.lifecycle import (
    DealPurchase,
    OnboardingPlan,
    Product,
    Quote,
    QuoteAcceptance,
    QuoteLine,
)
from app.services.audit import emit_event, write_audit
from app.services.crm import STAGE_PROBABILITY, add_activity
from app.services.customer_lifecycle import select_customer_owner
from app.services.demo_guard import EXPIRED_BLOCK, PREPARED_BLOCK, scope_for_execution
from app.services.journey_engine import link_journey
from app.services.product_context import CONTEXT_VERSION, context_for_lead
from app.services.provider_ops import begin_action, confirm_action
from app.services.purchase_followthrough import bind_purchase_onboarding, checklist_for_plan
from app.services.query import get_owned
from app.services.rbac import user_permissions

_FROZEN = {"approved", "sent", "accepted"}
_SOURCES = {"manual", "fixture", "document", "model"}
_MONEY = Decimal("0.01")
_NO_EXTERNAL = "This decision does not send a quote, collect payment, sign a contract, or provision a service."


class CommercialCloseError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _money(value: Decimal) -> str:
    return str(Decimal(value).quantize(_MONEY))


def _tenant(db: Session, tenant_id: UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise CommercialCloseError("The tenant was not found.", 404)
    return tenant


def _fixture_tenant(db: Session, tenant_id: UUID) -> bool:
    return _tenant(db, tenant_id).operating_mode != "LIVE"


def _lines(db: Session, quote_id: UUID) -> list[QuoteLine]:
    return list(
        db.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote_id, QuoteLine.deleted_at.is_(None)).order_by(QuoteLine.created_at.asc())).all()
    )


def _lead_for_opportunity(db: Session, tenant_id: UUID, opportunity: Opportunity) -> Lead | None:
    link = db.scalar(
        select(JourneyLink).where(
            JourneyLink.tenant_id == tenant_id,
            JourneyLink.entity_type == "opportunity",
            JourneyLink.entity_id == str(opportunity.id),
            JourneyLink.deleted_at.is_(None),
        )
    )
    if link is None or not link.journey_key.startswith("inbound:"):
        return None
    try:
        lead_id = UUID(link.journey_key.split(":", 1)[1])
    except ValueError:
        return None
    lead = db.get(Lead, lead_id)
    if lead is None or lead.tenant_id != tenant_id or lead.deleted_at is not None:
        return None
    if lead.account_id != opportunity.account_id:
        return None
    return lead


def quote_is_frozen(quote: Quote) -> bool:
    return quote.status in _FROZEN or quote.sent_at is not None or quote.accepted_at is not None


def freeze_quote_commercial(db: Session, quote: Quote) -> Quote:
    """Copy product facts onto empty snapshot fields. Filled fields stay as quoted."""
    if quote_is_frozen(quote) and quote.context_json:
        return quote
    lines = _lines(db, quote.id)
    opportunity = db.get(Opportunity, quote.opportunity_id)
    lead = _lead_for_opportunity(db, quote.tenant_id, opportunity) if opportunity is not None else None
    context = context_for_lead(db, quote.tenant_id, lead) if lead is not None and lead.operating_plan_id else None
    if lead is not None and lead.operating_plan_id and quote.operating_plan_id is None:
        quote.operating_plan_id = lead.operating_plan_id
    currencies: set[str] = set()
    facts: list[dict] = []
    plan_product: Product | None = None
    for line in lines:
        product = db.get(Product, line.product_id)
        if product is not None and product.tenant_id == quote.tenant_id:
            if not line.sku:
                line.sku = product.sku
            if not line.customer_facing_name:
                if context is not None and context.customer_facing_name and product.id == _plan_product_id(db, lead):
                    line.customer_facing_name = context.customer_facing_name
                else:
                    line.customer_facing_name = product.name
            if not line.offer_label:
                line.offer_label = product.kind
            plan_product = product
            if product.currency:
                currencies.add(product.currency)
        facts.append(
            {
                "product_id": str(line.product_id),
                "sku": line.sku,
                "customer_facing_name": line.customer_facing_name,
                "offer_label": line.offer_label,
                "catalogue_name": product.name if product is not None else "",
                "kind": product.kind if product is not None else "",
                "quantity": line.quantity,
                "unit_price": _money(line.unit_price),
                "line_total": _money(line.line_total),
                "currency": product.currency if product is not None else "",
            }
        )
    if not quote.currency and len(currencies) == 1:
        quote.currency = next(iter(currencies))
    if len(currencies) > 1:
        quote.currency = ""
    if not quote.customer_facing_name:
        quote.customer_facing_name = "; ".join(row.customer_facing_name for row in lines if row.customer_facing_name)
    if not quote.sku:
        quote.sku = "; ".join(row.sku for row in lines if row.sku)
    if not quote.offer_label:
        quote.offer_label = "; ".join(row.offer_label for row in lines if row.offer_label)
    quote.context_version = context.as_dict().get("version", CONTEXT_VERSION) if context is not None else "catalogue-row"
    quote.context_json = json.dumps(
        {
            "version": quote.context_version,
            "operating_plan_id": str(quote.operating_plan_id) if quote.operating_plan_id else "",
            "lines": facts,
            "terms": quote.terms,
            "scope_text": quote.scope_text,
            "billing_cadence": quote.billing_cadence,
            "service_start": quote.service_start.isoformat() if quote.service_start else "",
            "service_end": quote.service_end.isoformat() if quote.service_end else "",
            "valid_until": quote.valid_until.isoformat() if quote.valid_until else "",
            "discount_pct": quote.discount_pct if quote.discount_pct else None,
            "tax_pct": quote.tax_pct if quote.tax_pct else None,
            "subtotal": _money(quote.subtotal),
            "total": _money(quote.total),
            "currency": quote.currency,
            "sources": context.as_dict().get("sources", {}) if context is not None else {"catalogue_name": plan_product.name if plan_product else ""},
        }
    )
    if quote.fixture is False:
        quote.fixture = _fixture_tenant(db, quote.tenant_id)
    return quote


def _plan_product_id(db: Session, lead: Lead | None) -> UUID | None:
    if lead is None or lead.operating_plan_id is None:
        return None
    from app.models.operating_plan import OperatingPlan

    plan = db.get(OperatingPlan, lead.operating_plan_id)
    if plan is None or plan.tenant_id != lead.tenant_id:
        return None
    return plan.product_id


def apply_quote_terms(
    quote: Quote,
    *,
    terms: str = "",
    scope_text: str = "",
    billing_cadence: str = "",
    service_start=None,
    service_end=None,
    valid_until=None,
    offer_label: str = "",
) -> None:
    if terms:
        quote.terms = terms
    if scope_text:
        quote.scope_text = scope_text
    if billing_cadence:
        quote.billing_cadence = billing_cadence
    if service_start is not None:
        quote.service_start = service_start
    if service_end is not None:
        quote.service_end = service_end
    if valid_until is not None:
        quote.valid_until = valid_until
    if offer_label:
        quote.offer_label = offer_label


def issue_quote(db: Session, *, tenant_id: UUID, actor_id: UUID, quote: Quote) -> Quote:
    if quote.tenant_id != tenant_id:
        raise CommercialCloseError("The quote belongs to a different tenant.", 404)
    if quote.status == "accepted":
        raise CommercialCloseError("An accepted quote version stays unchanged.")
    if quote.approval_required or (quote.discount_pct >= 10 and quote.status != "approved"):
        raise CommercialCloseError("This discount needs approval before the quote can be issued.")
    if quote.status == "approved":
        return quote
    if quote.status != "draft":
        raise CommercialCloseError("Only a draft quote can be issued.")
    freeze_quote_commercial(db, quote)
    quote.status = "approved"
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="quote.issued",
        entity_type="quote",
        entity_id=str(quote.id),
        after={"version": quote.version, "total": _money(quote.total), "currency": quote.currency},
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="quote.issued",
        entity_type="quote",
        entity_id=str(quote.id),
        payload={"version": quote.version, "opportunity_id": str(quote.opportunity_id)},
    )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="quote",
        entity_id=str(quote.id),
        activity_type="quote_issued",
        title="Quote version issued",
        body=f"Version {quote.version} is approved for acceptance. It was not sent.",
    )
    return quote


def clone_quote_edit(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    quote: Quote,
    product: Product,
    quantity: int,
    unit_price: Decimal,
) -> Quote:
    """A frozen version stays as issued. The edit is a new draft."""
    version = int(
        db.scalar(select(func.max(Quote.version)).where(Quote.tenant_id == tenant_id, Quote.opportunity_id == quote.opportunity_id, Quote.deleted_at.is_(None)))
        or quote.version
        or 1
    )
    successor = Quote(
        tenant_id=tenant_id,
        created_by=actor_id,
        opportunity_id=quote.opportunity_id,
        status="draft",
        discount_pct=quote.discount_pct,
        tax_pct=quote.tax_pct,
        version=version + 1,
        terms=quote.terms,
        currency=quote.currency,
        customer_facing_name=quote.customer_facing_name,
        offer_label=quote.offer_label,
        sku=quote.sku,
        scope_text=quote.scope_text,
        billing_cadence=quote.billing_cadence,
        service_start=quote.service_start,
        service_end=quote.service_end,
        valid_until=quote.valid_until,
        operating_plan_id=quote.operating_plan_id,
        contact_id=quote.contact_id,
        parent_quote_id=quote.id,
        context_version=quote.context_version,
        fixture=quote.fixture,
    )
    db.add(successor)
    db.flush()
    for line in _lines(db, quote.id):
        db.add(
            QuoteLine(
                tenant_id=tenant_id,
                created_by=actor_id,
                quote_id=successor.id,
                product_id=line.product_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_total=line.line_total,
                customer_facing_name=line.customer_facing_name,
                offer_label=line.offer_label,
                sku=line.sku,
            )
        )
    quantity = max(1, quantity)
    db.add(
        QuoteLine(
            tenant_id=tenant_id,
            created_by=actor_id,
            quote_id=successor.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=unit_price,
            line_total=(unit_price * quantity).quantize(_MONEY),
        )
    )
    db.flush()
    from app.services.lifecycle import recompute_quote

    recompute_quote(db, successor)
    freeze_quote_commercial(db, successor)
    if successor.approval_required:
        db.add(
            AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="quote.discount",
                title=f"Approve {successor.discount_pct}% discount on quote",
                payload_json=json.dumps(
                    {
                        "quote_id": str(successor.id),
                        "total": str(successor.total),
                        "version": int(successor.version or 1),
                        "discount_pct": successor.discount_pct,
                    }
                ),
                status="pending",
            )
        )
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="quote.versioned",
        entity_type="quote",
        entity_id=str(successor.id),
        after={"parent_quote_id": str(quote.id), "version": successor.version},
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="quote.versioned",
        entity_type="quote",
        entity_id=str(successor.id),
        payload={"parent_quote_id": str(quote.id), "version": successor.version},
    )
    return successor


def record_acceptance(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    quote: Quote,
    contact_id: UUID | None,
    relationship: str,
    source: str,
    evidence: str,
) -> QuoteAcceptance:
    source = (source or "manual").strip().lower()
    if source == "provider":
        raise CommercialCloseError("No acceptance provider is connected. Provider-verified acceptance is not recorded.")
    if quote.tenant_id != tenant_id:
        raise CommercialCloseError("The quote belongs to a different tenant.", 404)
    if quote.status != "approved":
        raise CommercialCloseError("Only an approved quote version can be accepted.")
    if quote.superseded_by_id is not None:
        raise CommercialCloseError("This quote version was superseded.")
    if source not in _SOURCES:
        raise CommercialCloseError("Acceptance source is not recognized.")
    existing = db.scalar(
        select(QuoteAcceptance).where(
            QuoteAcceptance.tenant_id == tenant_id,
            QuoteAcceptance.quote_id == quote.id,
            QuoteAcceptance.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing
    contact = None
    if contact_id is not None:
        contact = db.get(Contact, contact_id)
        if contact is None or contact.tenant_id != tenant_id or contact.deleted_at is not None:
            raise CommercialCloseError("The accepting person was not found.", 404)
    relationship = relationship.strip()
    review = "recorded"
    if source in {"document", "model"}:
        review = "needs_review"
    if contact is None or not relationship:
        review = "incomplete"
    moment = datetime.now(UTC)
    row = QuoteAcceptance(
        tenant_id=tenant_id,
        created_by=actor_id,
        quote_id=quote.id,
        contact_id=contact.id if contact else None,
        relationship=relationship,
        accepted_at=moment,
        source=source,
        evidence=evidence.strip(),
        review_state=review,
        fixture=quote.fixture or source == "fixture",
    )
    db.add(row)
    quote.status = "accepted"
    quote.accepted_at = moment
    quote.contact_id = contact.id if contact else quote.contact_id
    older = db.scalars(
        select(Quote).where(
            Quote.tenant_id == tenant_id,
            Quote.opportunity_id == quote.opportunity_id,
            Quote.id != quote.id,
            Quote.status == "accepted",
            Quote.superseded_by_id.is_(None),
            Quote.deleted_at.is_(None),
        )
    ).all()
    for prior in older:
        if int(prior.version or 1) < int(quote.version or 1):
            prior.superseded_by_id = quote.id
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="quote.accepted",
        entity_type="quote",
        entity_id=str(quote.id),
        after={"version": quote.version, "source": source, "review_state": review, "relationship": relationship},
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="quote.accepted",
        entity_type="quote",
        entity_id=str(quote.id),
        payload={"source": source, "review_state": review, "opportunity_id": str(quote.opportunity_id)},
    )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="quote",
        entity_id=str(quote.id),
        activity_type="quote_accepted",
        title="Quote acceptance recorded",
        body=f"Source {source}. Review {review}. No customer was created.",
    )
    return row


def review_acceptance(db: Session, *, tenant_id: UUID, actor_id: UUID, quote: Quote, note: str) -> QuoteAcceptance:
    row = db.scalar(
        select(QuoteAcceptance).where(
            QuoteAcceptance.tenant_id == tenant_id,
            QuoteAcceptance.quote_id == quote.id,
            QuoteAcceptance.deleted_at.is_(None),
        )
    )
    if row is None:
        raise CommercialCloseError("No acceptance is recorded.")
    if row.source not in {"document", "model"}:
        raise CommercialCloseError("Only document or model evidence waits for review.")
    if row.review_state == "incomplete":
        raise CommercialCloseError("Acceptance is incomplete. The accepting relationship is missing.")
    row.review_state = "reviewed"
    if note.strip():
        row.evidence = f"{row.evidence}\nReview: {note.strip()}".strip()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="quote.acceptance_reviewed",
        entity_type="quote",
        entity_id=str(quote.id),
        after={"review_state": "reviewed", "provider_verified": False},
    )
    return row


def _acceptance(db: Session, tenant_id: UUID, quote_id: UUID) -> QuoteAcceptance | None:
    return db.scalar(
        select(QuoteAcceptance).where(
            QuoteAcceptance.tenant_id == tenant_id,
            QuoteAcceptance.quote_id == quote_id,
            QuoteAcceptance.deleted_at.is_(None),
        )
    )


def close_blockers(db: Session, *, tenant_id: UUID, opportunity: Opportunity, quote: Quote) -> list[str]:
    blockers: list[str] = []
    if quote.tenant_id != tenant_id or quote.opportunity_id != opportunity.id:
        blockers.append("The quote does not belong to this opportunity.")
        return blockers
    if quote.status != "accepted":
        blockers.append("The quote version is not accepted.")
    if quote.superseded_by_id is not None:
        blockers.append("This quote version was superseded.")
    acceptance = _acceptance(db, tenant_id, quote.id)
    if acceptance is None:
        blockers.append("No acceptance is recorded.")
    else:
        if acceptance.review_state == "incomplete" or not acceptance.relationship.strip() or acceptance.contact_id is None:
            blockers.append("Acceptance is incomplete. The accepting person and relationship are required.")
        elif acceptance.source in {"document", "model"} and acceptance.review_state != "reviewed":
            blockers.append("This evidence is for review. It is not proof of acceptance or authority.")
        elif acceptance.review_state == "blocked":
            blockers.append("Acceptance is blocked.")
        if acceptance.contact_id is not None:
            contact = db.get(Contact, acceptance.contact_id)
            if contact is None or contact.tenant_id != tenant_id or contact.account_id != opportunity.account_id:
                blockers.append("The accepting person is not recorded on this account.")
    conflict = db.scalar(
        select(Quote.id).where(
            Quote.tenant_id == tenant_id,
            Quote.opportunity_id == opportunity.id,
            Quote.id != quote.id,
            Quote.status == "accepted",
            Quote.superseded_by_id.is_(None),
            Quote.deleted_at.is_(None),
        )
    )
    if conflict is not None:
        blockers.append("Conflicting acceptance is recorded.")
    valid = _aware(quote.valid_until)
    if valid is not None and valid <= datetime.now(UTC):
        blockers.append("The quote validity has expired.")
    if not (quote.currency or "").strip():
        blockers.append("The quote has no single currency. No conversion is recorded.")
    if not (quote.customer_facing_name or "").strip() or not (quote.sku or "").strip():
        blockers.append("The quoted product snapshot is incomplete.")
    if not _lines(db, quote.id):
        blockers.append("The quote has no lines.")
    return blockers


def _external_block(db: Session, tenant_id: UUID) -> str:
    tenant = _tenant(db, tenant_id)
    scope = scope_for_execution(db, tenant_id)
    if scope is None:
        if tenant.operating_mode == "DEMO":
            return "Quote delivery, payment, and provisioning stay outside this demonstration. Nothing was sent."
        return ""
    expires = _aware(scope.expires_at)
    if expires is not None and expires <= datetime.now(UTC):
        return EXPIRED_BLOCK
    if scope.status == "prepared":
        return PREPARED_BLOCK
    if scope.status != "authorized":
        return "Quote delivery, payment, and provisioning stay outside this demonstration. Nothing was sent."
    return ""


def _snapshot(quote: Quote) -> str:
    try:
        body = json.loads(quote.context_json or "{}")
    except json.JSONDecodeError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    body["currency"] = quote.currency
    body["total"] = _money(quote.total)
    body["customer_facing_name"] = quote.customer_facing_name
    body["sku"] = quote.sku
    body["offer_label"] = quote.offer_label
    body["scope_text"] = quote.scope_text
    body["terms"] = quote.terms
    body["billing_cadence"] = quote.billing_cadence
    body["quote_id"] = str(quote.id)
    body["version"] = quote.version
    lines = body.get("lines") if isinstance(body.get("lines"), list) else []
    kinds = [str(row.get("kind") or "") for row in lines if isinstance(row, dict) and str(row.get("kind") or "").strip()]
    if len(set(kinds)) > 1:
        body["product_kind"] = "mixed"
    elif kinds:
        body["product_kind"] = kinds[0]
    else:
        body["product_kind"] = str(body.get("product_kind") or "")
    return json.dumps(body)


def _missing_info(quote: Quote, contact: Contact | None) -> list[str]:
    missing: list[str] = []
    if contact is None or not (contact.email or "").strip():
        missing.append("Billing contact email")
    if quote.service_start is None:
        missing.append("Service start")
    if quote.service_end is None:
        missing.append("Service end")
    if not (quote.billing_cadence or "").strip():
        missing.append("Billing cadence")
    return missing


def _owner_name(db: Session, tenant_id: UUID, owner_id: UUID | None) -> str:
    if owner_id is None:
        return ""
    owner = db.get(User, owner_id)
    if owner is None or owner.tenant_id != tenant_id:
        return ""
    return owner.name or ""


def _journey_key(db: Session, tenant_id: UUID, opportunity: Opportunity) -> str:
    link = db.scalar(
        select(JourneyLink).where(
            JourneyLink.tenant_id == tenant_id,
            JourneyLink.entity_type == "opportunity",
            JourneyLink.entity_id == str(opportunity.id),
            JourneyLink.deleted_at.is_(None),
        )
    )
    if link is not None:
        return link.journey_key
    return f"opportunity:{opportunity.id}"


def commercial_view(db: Session, *, tenant_id: UUID, opportunity_id: UUID) -> dict:
    opportunity = get_owned(db, Opportunity, tenant_id, opportunity_id)
    quotes = list(
        db.scalars(
            select(Quote)
            .where(Quote.tenant_id == tenant_id, Quote.opportunity_id == opportunity.id, Quote.deleted_at.is_(None))
            .order_by(Quote.version.desc(), Quote.created_at.desc())
        ).all()
    )
    purchase = db.scalar(
        select(DealPurchase).where(
            DealPurchase.tenant_id == tenant_id,
            DealPurchase.opportunity_id == opportunity.id,
            DealPurchase.deleted_at.is_(None),
        )
    )
    selected = next((row for row in quotes if purchase and row.id == purchase.quote_id), None)
    if selected is None:
        selected = next((row for row in quotes if row.status == "accepted" and row.superseded_by_id is None), None)
    if selected is None and quotes:
        selected = quotes[0]
    acceptance = _acceptance(db, tenant_id, selected.id) if selected is not None else None
    blockers = close_blockers(db, tenant_id=tenant_id, opportunity=opportunity, quote=selected) if selected is not None else ["No quote version is recorded."]
    if purchase is not None and purchase.status == "won":
        blockers = []
    if purchase is not None and purchase.status == "reversed":
        blockers = ["This purchase was reversed. A new close needs a new opportunity."]
    plan = None
    task = None
    if purchase is not None and purchase.onboarding_plan_id:
        plan = db.get(OnboardingPlan, purchase.onboarding_plan_id)
    if purchase is not None and purchase.task_id:
        task = db.get(Task, purchase.task_id)
    customer = None
    if purchase is not None and purchase.customer_id:
        customer = db.get(Customer, purchase.customer_id)
    contact = db.get(Contact, acceptance.contact_id) if acceptance and acceptance.contact_id else None
    missing = _missing_info(selected, contact) if selected is not None else []
    external = _external_block(db, tenant_id)
    return {
        "opportunity_id": opportunity.id,
        "account_id": opportunity.account_id,
        "stage": opportunity.stage,
        "quote_id": selected.id if selected else None,
        "quote_version": selected.version if selected else None,
        "quote_status": selected.status if selected else "",
        "currency": selected.currency if selected else "",
        "subtotal": selected.subtotal if selected else Decimal("0"),
        "total": selected.total if selected else Decimal("0"),
        "discount_pct": selected.discount_pct if selected and selected.discount_pct else None,
        "tax_pct": selected.tax_pct if selected and selected.tax_pct else None,
        "customer_facing_name": selected.customer_facing_name if selected else "",
        "offer_label": selected.offer_label if selected else "",
        "sku": selected.sku if selected else "",
        "scope_text": selected.scope_text if selected else "",
        "terms": selected.terms if selected else "",
        "billing_cadence": selected.billing_cadence if selected else "",
        "service_start": selected.service_start if selected else None,
        "service_end": selected.service_end if selected else None,
        "valid_until": selected.valid_until if selected else None,
        "acceptance_source": acceptance.source if acceptance else "",
        "acceptance_review": acceptance.review_state if acceptance else "",
        "acceptance_relationship": acceptance.relationship if acceptance else "",
        "acceptance_evidence": acceptance.evidence if acceptance else "",
        "provider_verified": False,
        "blockers": blockers,
        "ready": not blockers and (purchase is None or purchase.status != "won"),
        "won": bool(purchase and purchase.status == "won"),
        "purchase_status": purchase.status if purchase else "",
        "payment_status": purchase.payment_status if purchase else "",
        "customer_id": customer.id if customer else None,
        "customer_status": customer.status if customer else "",
        "activated": bool(customer and customer.activated_at),
        "onboarding_plan_id": plan.id if plan else None,
        "onboarding_status": plan.status if plan else "",
        "onboarding_next_action": plan.next_action if plan else "",
        "onboarding_blocker": plan.blocker if plan else "",
        "task_id": task.id if task else None,
        "task_status": task.status if task else "",
        "owner_id": task.owner_id if task else None,
        "owner_name": _owner_name(db, tenant_id, task.owner_id if task else None),
        "missing_information": missing,
        "fixture": bool((purchase and purchase.fixture) or (selected and selected.fixture)),
        "external_block": external,
        "external_released": False,
        "checklist": checklist_for_plan(db, tenant_id=tenant_id, plan=plan),
        "decided_at": purchase.decided_at if purchase else None,
        "reversal_reason": purchase.reversal_reason if purchase else "",
        "note": _NO_EXTERNAL,
    }


def decide_close_won(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    opportunity_id: UUID,
    quote_id: UUID,
    note: str = "",
) -> dict:
    actor = db.get(User, actor_id)
    if actor is None or not actor.is_active or actor.tenant_id != tenant_id:
        raise CommercialCloseError("The operator was not found.", 404)
    if "opportunities.close" not in user_permissions(db, actor):
        raise CommercialCloseError("Permission denied.", 403)
    opportunity = get_owned(db, Opportunity, tenant_id, opportunity_id)
    quote = get_owned(db, Quote, tenant_id, quote_id)
    if quote.opportunity_id != opportunity.id:
        raise CommercialCloseError("The quote does not belong to this opportunity.")
    existing = db.scalar(
        select(DealPurchase).where(
            DealPurchase.tenant_id == tenant_id,
            DealPurchase.opportunity_id == opportunity.id,
            DealPurchase.deleted_at.is_(None),
        )
    )
    if existing is not None and existing.status == "won":
        if existing.quote_id != quote.id:
            raise CommercialCloseError("This opportunity already has a purchase snapshot.")
        prior_acceptance = _acceptance(db, tenant_id, quote.id)
        prior_contact = db.get(Contact, prior_acceptance.contact_id) if prior_acceptance is not None and prior_acceptance.contact_id else None
        bind_purchase_onboarding(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            purchase=existing,
            quote=quote,
            contact=prior_contact,
        )
        return commercial_view(db, tenant_id=tenant_id, opportunity_id=opportunity.id)
    if existing is not None and existing.status == "reversed":
        raise CommercialCloseError("This purchase was reversed. A new close needs a new opportunity.")
    blockers = close_blockers(db, tenant_id=tenant_id, opportunity=opportunity, quote=quote)
    if blockers:
        raise CommercialCloseError(blockers[0])
    account = get_owned(db, Account, tenant_id, opportunity.account_id)
    acceptance = _acceptance(db, tenant_id, quote.id)
    if acceptance is None:
        raise CommercialCloseError("No acceptance is recorded.")
    contact = db.get(Contact, acceptance.contact_id) if acceptance.contact_id else None
    key = f"commercial.close:{opportunity.id}:{quote.id}"
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="commercial.close_won",
        idempotency_key=key,
        provider="commercial-record",
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        request_summary=f"quote {quote.id} version {quote.version}",
    )
    if action.status == "CONFIRMED" and action.external_id:
        return commercial_view(db, tenant_id=tenant_id, opportunity_id=opportunity.id)
    customer = db.scalar(
        select(Customer).where(Customer.tenant_id == tenant_id, Customer.account_id == account.id, Customer.deleted_at.is_(None))
    )
    created_customer = customer is None
    if customer is None:
        customer = Customer(
            tenant_id=tenant_id,
            created_by=actor_id,
            account_id=account.id,
            opportunity_id=opportunity.id,
            status="onboarding",
            lifecycle_state="NEW_CUSTOMER",
            arr=Decimal("0"),
        )
        db.add(customer)
        db.flush()
    else:
        prior = db.scalar(
            select(DealPurchase.id).where(
                DealPurchase.tenant_id == tenant_id,
                DealPurchase.customer_id == customer.id,
                DealPurchase.opportunity_id != opportunity.id,
                DealPurchase.status == "won",
                DealPurchase.deleted_at.is_(None),
            )
        )
        if customer.opportunity_id is None and prior is None:
            customer.opportunity_id = opportunity.id
    if account.ownership != "customer":
        account.ownership = "customer"
    owner = select_customer_owner(db, tenant_id=tenant_id, opportunity=opportunity, account=account)
    missing = _missing_info(quote, contact)
    next_action = "Collect the missing customer information." if missing else "Confirm the setup tasks with the customer."
    blocker = "Required customer information is missing." if missing else ""
    plan = OnboardingPlan(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer.id,
        opportunity_id=opportunity.id,
        quote_id=quote.id,
        status="open",
        objective=f"Onboard {quote.customer_facing_name}. Scope: {quote.scope_text or 'not recorded'}.",
        next_action=next_action,
        blocker=blocker,
    )
    db.add(plan)
    db.flush()
    task = Task(
        tenant_id=tenant_id,
        created_by=actor_id,
        title=f"Onboard {quote.customer_facing_name}",
        description=(
            f"Opportunity {opportunity.id}. Quote {quote.id} version {quote.version}. "
            f"Product {quote.customer_facing_name}. SKU {quote.sku}. Offer {quote.offer_label}. "
            f"Scope {quote.scope_text or 'not recorded'}. Terms {quote.terms or 'not recorded'}. "
            f"Amount {quote.currency} {_money(quote.total)}. "
            f"Missing: {', '.join(missing) if missing else 'none recorded'}. "
            "Payment is not recorded. The contract is not executed. The account is not provisioned. "
            "The service is not delivered. Onboarding is not complete."
        ),
        status="open",
        priority="high",
        owner_id=owner.id if owner else None,
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        source="workflow",
    )
    db.add(task)
    db.flush()
    moment = datetime.now(UTC)
    purchase = DealPurchase(
        tenant_id=tenant_id,
        created_by=actor_id,
        opportunity_id=opportunity.id,
        quote_id=quote.id,
        customer_id=customer.id,
        account_id=account.id,
        onboarding_plan_id=plan.id,
        task_id=task.id,
        currency=quote.currency,
        amount=quote.total,
        snapshot_json=_snapshot(quote),
        decided_by=actor_id,
        decided_at=moment,
        evidence_note=note.strip() or acceptance.evidence,
        status="won",
        payment_status="",
        fixture=quote.fixture,
    )
    db.add(purchase)
    db.flush()
    plan.purchase_id = purchase.id
    bind_purchase_onboarding(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        purchase=purchase,
        quote=quote,
        contact=contact,
    )
    from app.services.ml.history import record_opportunity_fields

    record_opportunity_fields(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        opportunity_id=opportunity.id,
        changes={"stage": (opportunity.stage, "closed_won"), "probability": (opportunity.probability, 100)},
    )
    opportunity.stage = "closed_won"
    opportunity.probability = 100
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="commercial.close_won",
        title=f"Close won {opportunity.name}",
        payload_json=json.dumps({"opportunity_id": str(opportunity.id), "quote_id": str(quote.id), "purchase_id": str(purchase.id)}),
        status="approved",
        decided_by=actor_id,
        decision_note=note.strip() or "Operator close-won decision.",
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        idempotency_key=key,
    )
    db.add(approval)
    confirm_action(action, provider="commercial-record", external_id=str(purchase.id), response_summary="purchase recorded")
    journey = _journey_key(db, tenant_id, opportunity)
    link_journey(db, tenant_id=tenant_id, actor_id=actor_id, journey_key=journey, entity_type="opportunity", entity_id=str(opportunity.id), role="deal")
    link_journey(db, tenant_id=tenant_id, actor_id=actor_id, journey_key=journey, entity_type="quote", entity_id=str(quote.id), role="accepted_quote")
    link_journey(db, tenant_id=tenant_id, actor_id=actor_id, journey_key=journey, entity_type="customer", entity_id=str(customer.id), role="customer")
    link_journey(db, tenant_id=tenant_id, actor_id=actor_id, journey_key=journey, entity_type="task", entity_id=str(task.id), role="onboarding")
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="commercial.close_won",
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        after={
            "quote_id": str(quote.id),
            "customer_id": str(customer.id),
            "purchase_id": str(purchase.id),
            "amount": _money(quote.total),
            "currency": quote.currency,
            "payment_status": "",
        },
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="commercial.close_won",
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        payload={"quote_id": str(quote.id), "purchase_id": str(purchase.id), "customer_id": str(customer.id)},
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="commercial.customer_linked",
        entity_type="customer",
        entity_id=str(customer.id),
        payload={"created": created_customer, "opportunity_id": str(opportunity.id)},
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="commercial.onboarding_opened",
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        payload={"plan_id": str(plan.id), "task_id": str(task.id), "purchase_id": str(purchase.id), "completed": False},
    )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        activity_type="close_won",
        title="Closed won",
        body=f"Quote version {quote.version}. {quote.currency} {_money(quote.total)}. Payment is not recorded.",
    )
    return commercial_view(db, tenant_id=tenant_id, opportunity_id=opportunity.id)


def correct_close_won(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    opportunity_id: UUID,
    reason: str,
) -> dict:
    actor = db.get(User, actor_id)
    if actor is None or actor.tenant_id != tenant_id or "opportunities.close" not in user_permissions(db, actor):
        raise CommercialCloseError("Permission denied.", 403)
    reason = reason.strip()
    if not reason:
        raise CommercialCloseError("A correction needs a recorded reason.")
    opportunity = get_owned(db, Opportunity, tenant_id, opportunity_id)
    purchase = db.scalar(
        select(DealPurchase).where(
            DealPurchase.tenant_id == tenant_id,
            DealPurchase.opportunity_id == opportunity.id,
            DealPurchase.deleted_at.is_(None),
        )
    )
    if purchase is None or purchase.status != "won":
        raise CommercialCloseError("There is no close-won purchase to correct.")
    purchase.status = "reversed"
    purchase.reversal_reason = reason
    purchase.reversed_by = actor_id
    purchase.reversed_at = datetime.now(UTC)
    from app.services.ml.history import record_opportunity_fields

    record_opportunity_fields(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        opportunity_id=opportunity.id,
        changes={"stage": (opportunity.stage, "commit")},
    )
    opportunity.stage = "commit"
    opportunity.probability = STAGE_PROBABILITY["commit"]
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="commercial.close_won_reversed",
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        after={"purchase_id": str(purchase.id), "reason": reason, "deleted": False},
    )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        activity_type="close_won_reversed",
        title="Close-won reversed",
        body=reason,
    )
    return commercial_view(db, tenant_id=tenant_id, opportunity_id=opportunity.id)


def _add(bucket: dict, currency: str, field: str, amount: Decimal) -> None:
    key = currency or "unspecified"
    row = bucket.setdefault(
        key,
        {
            "open_pipeline": "0.00",
            "quoted": "0.00",
            "accepted": "0.00",
            "closed_won": "0.00",
            "invoiced": None,
            "collected": None,
        },
    )
    current = Decimal(str(row[field] or "0"))
    row[field] = _money(current + amount)


def commercial_ledger(db: Session, tenant_id: UUID) -> dict:
    """Separate commercial figures. Currencies are not converted. Fixture rows stay apart."""
    real: dict = {}
    fixture: dict = {}
    opportunities = db.scalars(select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.deleted_at.is_(None))).all()
    for opportunity in opportunities:
        if opportunity.stage in {"closed_won", "closed_lost"}:
            continue
        latest = db.scalar(
            select(Quote)
            .where(Quote.tenant_id == tenant_id, Quote.opportunity_id == opportunity.id, Quote.deleted_at.is_(None))
            .order_by(Quote.version.desc())
        )
        currency = latest.currency if latest is not None and latest.currency else ""
        target = fixture if latest is not None and latest.fixture else real
        _add(target, currency, "open_pipeline", opportunity.amount or Decimal("0"))
    quotes = db.scalars(select(Quote).where(Quote.tenant_id == tenant_id, Quote.deleted_at.is_(None))).all()
    latest_ids: set[UUID] = set()
    by_opp: dict[UUID, Quote] = {}
    for quote in quotes:
        current = by_opp.get(quote.opportunity_id)
        if current is None or int(quote.version or 1) >= int(current.version or 1):
            by_opp[quote.opportunity_id] = quote
    latest_ids = {row.id for row in by_opp.values()}
    for quote in quotes:
        target = fixture if quote.fixture else real
        if quote.id in latest_ids and quote.superseded_by_id is None:
            _add(target, quote.currency, "quoted", quote.total or Decimal("0"))
        if quote.status == "accepted" and quote.superseded_by_id is None:
            _add(target, quote.currency, "accepted", quote.total or Decimal("0"))
    purchases = db.scalars(
        select(DealPurchase).where(DealPurchase.tenant_id == tenant_id, DealPurchase.status == "won", DealPurchase.deleted_at.is_(None))
    ).all()
    for purchase in purchases:
        target = fixture if purchase.fixture else real
        _add(target, purchase.currency, "closed_won", purchase.amount or Decimal("0"))
    return {
        "real": real,
        "fixture": fixture,
        "conversion": None,
        "invoiced": None,
        "collected": None,
        "note": "Currencies are not combined. Closed-won value is not collected cash or recognized revenue. No invoice or payment is recorded by this milestone.",
    }


def purchases_for_customer(db: Session, *, tenant_id: UUID, customer_id: UUID) -> list[dict]:
    rows = db.scalars(
        select(DealPurchase)
        .where(DealPurchase.tenant_id == tenant_id, DealPurchase.customer_id == customer_id, DealPurchase.deleted_at.is_(None))
        .order_by(DealPurchase.created_at.asc())
    ).all()
    payload = []
    for row in rows:
        quote = db.get(Quote, row.quote_id)
        plan = db.get(OnboardingPlan, row.onboarding_plan_id) if row.onboarding_plan_id else None
        task = db.get(Task, row.task_id) if row.task_id else None
        try:
            snapshot = json.loads(row.snapshot_json or "{}")
        except json.JSONDecodeError:
            snapshot = {}
        payload.append(
            {
                "id": row.id,
                "opportunity_id": row.opportunity_id,
                "quote_id": row.quote_id,
                "quote_version": quote.version if quote else None,
                "status": row.status,
                "currency": row.currency,
                "amount": row.amount,
                "payment_status": row.payment_status,
                "customer_facing_name": snapshot.get("customer_facing_name", "") if isinstance(snapshot, dict) else "",
                "sku": snapshot.get("sku", "") if isinstance(snapshot, dict) else "",
                "offer_label": snapshot.get("offer_label", "") if isinstance(snapshot, dict) else "",
                "scope_text": snapshot.get("scope_text", "") if isinstance(snapshot, dict) else "",
                "onboarding_status": plan.status if plan else "",
                "onboarding_next_action": plan.next_action if plan else "",
                "product_kind": snapshot.get("product_kind", "") if isinstance(snapshot, dict) else "",
                "billing_cadence": snapshot.get("billing_cadence", "") if isinstance(snapshot, dict) else "",
                "service_end": snapshot.get("service_end", "") if isinstance(snapshot, dict) else "",
                "provenance": "fixture" if row.fixture else "operator_recorded",
                "renewal_recorded": False,
                "checklist": checklist_for_plan(db, tenant_id=tenant_id, plan=plan),
                "task_status": task.status if task else "",
                "owner_name": _owner_name(db, tenant_id, task.owner_id if task else None),
                "fixture": row.fixture,
                "activated": False,
            }
        )
    return payload
