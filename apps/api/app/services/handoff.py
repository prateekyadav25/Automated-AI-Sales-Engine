import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.models.crm import Account, Activity, Contact, Customer, Opportunity
from app.models.lifecycle import MeetingRecord, Product, Quote, QuoteLine
from app.models.post_sale import HandoffPackage
from app.services.ai_artifacts import fingerprint, reuse_or_none, upsert_artifact
from app.services.audit import emit_event
from app.services.crm import add_activity

HANDOFF_FIELDS = [
    "customer_objectives",
    "business_problems",
    "purchased_solution",
    "products",
    "commercial_commitments",
    "implementation_commitments",
    "stakeholders",
    "economic_buyer",
    "champion",
    "technical_contacts",
    "known_risks",
    "expected_outcomes",
    "success_criteria",
    "important_dates",
    "open_actions",
]


def _unknown() -> None:
    return None


def gather_handoff_evidence(db: Session, *, tenant_id: UUID, customer: Customer, account: Account, opportunity: Opportunity | None) -> dict:
    contacts = db.scalars(
        select(Contact).where(Contact.tenant_id == tenant_id, Contact.account_id == account.id, Contact.deleted_at.is_(None))
    ).all()
    roles = {row.buying_role: f"{row.first_name} {row.last_name}".strip() for row in contacts if row.buying_role}
    meetings = []
    if opportunity:
        meetings = db.scalars(
            select(MeetingRecord).where(
                MeetingRecord.tenant_id == tenant_id,
                MeetingRecord.opportunity_id == opportunity.id,
                MeetingRecord.deleted_at.is_(None),
            )
        ).all()
    quotes = []
    products: list[str] = []
    commercial = None
    if opportunity:
        quotes = db.scalars(
            select(Quote).where(Quote.tenant_id == tenant_id, Quote.opportunity_id == opportunity.id, Quote.deleted_at.is_(None))
        ).all()
        for quote in quotes:
            lines = db.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id, QuoteLine.deleted_at.is_(None))).all()
            for line in lines:
                product = db.get(Product, line.product_id)
                if product:
                    products.append(product.name)
            commercial = {"quote_total": str(quote.total), "currency": getattr(product, "currency", None) if products else None}
    activities = db.scalars(
        select(Activity)
        .where(
            Activity.tenant_id == tenant_id,
            Activity.entity_type.in_(["opportunity", "account", "customer"]),
            Activity.entity_id.in_([str(opportunity.id) if opportunity else "", str(account.id), str(customer.id)]),
            Activity.deleted_at.is_(None),
        )
        .order_by(Activity.created_at.desc())
        .limit(12)
    ).all()
    open_actions = [row.title for row in activities if "next" in row.title.lower() or row.activity_type == "task"]
    payload = {
        "customer_objectives": opportunity.next_step or _unknown(),
        "business_problems": None,
        "purchased_solution": opportunity.name if opportunity else None,
        "products": products or None,
        "commercial_commitments": commercial,
        "implementation_commitments": None,
        "stakeholders": [{"name": f"{c.first_name} {c.last_name}".strip(), "role": c.buying_role, "title": c.title} for c in contacts] or None,
        "economic_buyer": roles.get("economic_buyer") or roles.get("decision_maker"),
        "champion": roles.get("champion"),
        "technical_contacts": roles.get("technical_buyer") or roles.get("influencer"),
        "known_risks": [row.summary for row in meetings if "risk" in (row.summary or "").lower()] or None,
        "expected_outcomes": None,
        "success_criteria": None,
        "important_dates": {
            "expected_close": opportunity.expected_close.isoformat() if opportunity and opportunity.expected_close else None,
            "meetings": [row.occurred_at.isoformat() if row.occurred_at else None for row in meetings],
        },
        "open_actions": open_actions or None,
        "account_name": account.name,
        "industry": account.industry or None,
    }
    missing = [key for key in HANDOFF_FIELDS if payload.get(key) in (None, "", [], {})]
    return {"payload": payload, "missing": missing}


def run_handoff_agent(evidence: dict) -> dict:
    llm = get_llm_provider()
    result = llm.complete(
        json.dumps(evidence, default=str),
        system=(
            "You are HandoffAgent. Summarize only the supplied evidence. "
            "Identify missing handoff fields. Highlight risks. Generate a kickoff agenda. "
            "Never invent commercial terms, prices, or commitments. Unknown stays unknown. No tools."
        ),
    )
    return {"text": result.text, "provider": result.provider, "is_mock": result.is_mock}


def ensure_handoff(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    customer: Customer,
    account: Account,
    opportunity: Opportunity | None,
) -> HandoffPackage:
    existing = db.scalar(
        select(HandoffPackage).where(
            HandoffPackage.tenant_id == tenant_id,
            HandoffPackage.customer_id == customer.id,
            HandoffPackage.deleted_at.is_(None),
        )
    )
    evidence = gather_handoff_evidence(db, tenant_id=tenant_id, customer=customer, account=account, opportunity=opportunity)
    source = fingerprint(evidence)
    if existing is not None and existing.source_fingerprint == source:
        return existing
    reused = reuse_or_none(
        db,
        tenant_id=tenant_id,
        kind="handoff",
        entity_type="customer",
        entity_id=str(customer.id),
        source_fingerprint=source,
    )
    if reused is None:
        generated = run_handoff_agent(evidence)
        reused = upsert_artifact(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            kind="handoff",
            entity_type="customer",
            entity_id=str(customer.id),
            title="Sales-to-success handoff",
            content={"summary": generated["text"], "evidence": evidence},
            source_fingerprint=source,
            provider=generated["provider"],
            is_mock=generated["is_mock"],
        )
        agenda = generated["text"]
    else:
        try:
            agenda = json.loads(reused.content_json).get("summary") or ""
        except json.JSONDecodeError:
            agenda = reused.content_json
    risks = []
    if evidence["missing"]:
        risks.append("Handoff is incomplete; unknown fields were not invented.")
    if existing is None:
        existing = HandoffPackage(
            tenant_id=tenant_id,
            created_by=actor_id,
            customer_id=customer.id,
            account_id=account.id,
            opportunity_id=opportunity.id if opportunity else None,
            status="ready",
            payload_json=json.dumps(evidence["payload"], default=str),
            missing_fields_json=json.dumps(evidence["missing"]),
            risks_json=json.dumps(risks),
            kickoff_agenda=agenda[:4000],
            source_fingerprint=source,
        )
        db.add(existing)
        db.flush()
        emit_event(
            db,
            tenant_id=tenant_id,
            event_type="handoff.created",
            entity_type="customer",
            entity_id=str(customer.id),
            payload={"handoff_id": str(existing.id)},
        )
        add_activity(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="customer",
            entity_id=str(customer.id),
            activity_type="handoff",
            title="Handoff package created",
            body="Evidence-supported sales-to-success handoff. Unknown fields stay unknown.",
            actor_type="ai",
        )
        return existing
    existing.payload_json = json.dumps(evidence["payload"], default=str)
    existing.missing_fields_json = json.dumps(evidence["missing"])
    existing.risks_json = json.dumps(risks)
    existing.kickoff_agenda = agenda[:4000]
    existing.source_fingerprint = source
    existing.status = "ready"
    return existing
