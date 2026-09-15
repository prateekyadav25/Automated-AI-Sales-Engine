import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.models.ai import AIApproval
from app.models.crm import Account, Customer, Opportunity
from app.models.lifecycle import Product, WhitespaceCell
from app.models.post_sale import ExpansionRecommendation, ProductRelationship, ProductUsageSnapshot
from app.services.ai_artifacts import fingerprint, reuse_or_none, upsert_artifact
from app.services.audit import emit_event
from app.services.crm import add_activity
from app.services.lifecycle import fill_whitespace


def ensure_relationships(db: Session, *, tenant_id: UUID, actor_id: UUID) -> int:
    products = db.scalars(select(Product).where(Product.tenant_id == tenant_id, Product.deleted_at.is_(None))).all()
    created = 0
    for index, product in enumerate(products):
        if index + 1 >= len(products):
            continue
        related = products[index + 1]
        exists = db.scalar(
            select(ProductRelationship).where(
                ProductRelationship.tenant_id == tenant_id,
                ProductRelationship.product_id == product.id,
                ProductRelationship.related_product_id == related.id,
                ProductRelationship.relationship == "complementary",
            )
        )
        if exists is None:
            db.add(
                ProductRelationship(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    product_id=product.id,
                    related_product_id=related.id,
                    relationship="complementary",
                    weight=55,
                    notes="Catalog adjacency. Not an LLM invention.",
                )
            )
            created += 1
    return created


def refresh_whitespace(db: Session, *, tenant_id: UUID, actor_id: UUID, account: Account) -> list[WhitespaceCell]:
    products = db.scalars(select(Product).where(Product.tenant_id == tenant_id, Product.deleted_at.is_(None))).all()
    return fill_whitespace(db, tenant_id=tenant_id, actor_id=actor_id, account=account, products=products)


def _owned_product_ids(db: Session, tenant_id: UUID, opportunity_id: UUID | None) -> set[UUID]:
    if not opportunity_id:
        return set()
    from app.models.lifecycle import Quote, QuoteLine

    quotes = db.scalars(select(Quote).where(Quote.tenant_id == tenant_id, Quote.opportunity_id == opportunity_id)).all()
    ids: set[UUID] = set()
    for quote in quotes:
        for line in db.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id)).all():
            ids.add(line.product_id)
    return ids


def detect_expansion(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, settings) -> list[ExpansionRecommendation]:
    account = db.get(Account, customer.account_id)
    if account is None:
        return []
    refresh_whitespace(db, tenant_id=tenant_id, actor_id=actor_id, account=account)
    ensure_relationships(db, tenant_id=tenant_id, actor_id=actor_id)
    db.flush()
    owned = _owned_product_ids(db, tenant_id, customer.opportunity_id)
    cells = db.scalars(
        select(WhitespaceCell).where(WhitespaceCell.tenant_id == tenant_id, WhitespaceCell.account_id == account.id, WhitespaceCell.deleted_at.is_(None))
    ).all()
    from app.services.usage_ingest import latest_rollup

    usage = db.scalar(
        select(ProductUsageSnapshot)
        .where(ProductUsageSnapshot.tenant_id == tenant_id, ProductUsageSnapshot.customer_id == customer.id)
        .order_by(ProductUsageSnapshot.created_at.desc())
    )
    rollup = latest_rollup(db, tenant_id, customer.id)
    created: list[ExpansionRecommendation] = []
    high_pct = int(getattr(settings, "high_utilization_pct", 85) or 85)
    seats_licensed = rollup.seats_licensed if rollup and not rollup.is_mock else (usage.seats_licensed if usage and not usage.is_mock else None)
    seats_used = rollup.seats_active if rollup and not rollup.is_mock else (usage.seats_used if usage and not usage.is_mock else None)
    utilization = rollup.utilization_pct if rollup and not rollup.is_mock else None
    if utilization is None and seats_licensed and seats_used:
        utilization = int(round(seats_used / seats_licensed * 100))
    live_ok = (rollup is not None and rollup.freshness_state == "LIVE" and not rollup.is_mock) or (
        usage is not None and usage.is_mock is False
    )
    if settings.upsell_enabled and live_ok and seats_licensed and seats_used:
        if utilization is not None and utilization >= high_pct:
            rec = _upsert_rec(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                customer=customer,
                account=account,
                kind="upsell",
                dimension="seats",
                title="Seat saturation",
                reason="Used seats are at or above 85% of licensed seats.",
                evidence={"seats_used": seats_used, "seats_licensed": seats_licensed, "threshold": high_pct},
                confidence=max(settings.minimum_expansion_confidence, 70),
                product_id=next(iter(owned), None),
            )
            if rec:
                created.append(rec)
                emit_event(db, tenant_id=tenant_id, event_type="upsell.detected", entity_type="customer", entity_id=str(customer.id), payload={"id": str(rec.id)})
    if settings.cross_sell_enabled or settings.expansion_enabled:
        for cell in cells:
            if cell.product_id in owned:
                continue
            related = False
            if owned:
                related = (
                    db.scalar(
                        select(ProductRelationship).where(
                            ProductRelationship.tenant_id == tenant_id,
                            ProductRelationship.product_id.in_(owned),
                            ProductRelationship.related_product_id == cell.product_id,
                        )
                    )
                    is not None
                )
            if not related and cell.propensity < 40:
                continue
            product = db.get(Product, cell.product_id)
            kind = "cross_sell" if related else "expansion"
            if kind == "cross_sell" and not settings.cross_sell_enabled:
                continue
            if kind == "expansion" and not settings.expansion_enabled:
                continue
            confidence = min(90, cell.propensity + (15 if related else 0))
            if confidence < settings.minimum_expansion_confidence:
                continue
            rec = _upsert_rec(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                customer=customer,
                account=account,
                kind=kind,
                dimension="product",
                title=f"{'Introduce' if kind == 'cross_sell' else 'Expand with'} {product.name if product else 'adjacent product'}",
                reason="Whitespace plus catalog relationship rules." if related else "Whitespace cell with industry propensity.",
                evidence={"propensity": cell.propensity, "related": related, "value_hint_is_list_price": True},
                confidence=confidence,
                product_id=cell.product_id,
            )
            if rec:
                created.append(rec)
                event = "cross_sell.detected" if kind == "cross_sell" else "expansion.detected"
                emit_event(db, tenant_id=tenant_id, event_type=event, entity_type="customer", entity_id=str(customer.id), payload={"id": str(rec.id)})
    if created:
        from app.services.nba import generate_for_expansion

        run_expansion_agent(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, recs=created)
        for rec in created:
            generate_for_expansion(db, tenant_id, rec, actor_id)
    return created


def _upsert_rec(db, *, tenant_id, actor_id, customer, account, kind, dimension, title, reason, evidence, confidence, product_id) -> ExpansionRecommendation | None:
    source = fingerprint({"kind": kind, "product_id": str(product_id or ""), "reason": reason})
    existing = db.scalar(
        select(ExpansionRecommendation).where(
            ExpansionRecommendation.tenant_id == tenant_id,
            ExpansionRecommendation.customer_id == customer.id,
            ExpansionRecommendation.kind == kind,
            ExpansionRecommendation.product_id == product_id,
            ExpansionRecommendation.deleted_at.is_(None),
        )
    )
    if existing is not None:
        existing.confidence = confidence
        existing.reason = reason
        existing.evidence_json = json.dumps(evidence, default=str)
        existing.source_fingerprint = source
        return None
    row = ExpansionRecommendation(
        tenant_id=tenant_id,
        created_by=actor_id,
        customer_id=customer.id,
        account_id=account.id,
        product_id=product_id,
        kind=kind,
        dimension=dimension,
        title=title,
        reason=reason,
        evidence_json=json.dumps(evidence, default=str),
        confidence=confidence,
        amount=None,
        ruleset_version="rules-v1",
        status="open",
        source_fingerprint=source,
    )
    db.add(row)
    db.flush()
    return row


def run_expansion_agent(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, recs: list[ExpansionRecommendation]) -> dict:
    payload = [{"title": row.title, "kind": row.kind, "reason": row.reason, "amount": None} for row in recs]
    source = fingerprint(payload)
    reused = reuse_or_none(db, tenant_id=tenant_id, kind="expansion_hypothesis", entity_type="customer", entity_id=str(customer.id), source_fingerprint=source)
    if reused is None:
        llm = get_llm_provider()
        result = llm.complete(
            json.dumps(payload, default=str),
            system="You are ExpansionAgent. Analyze footprint and whitespace. Do not invent revenue. Amount stays null. No tools.",
        )
        reused = upsert_artifact(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            kind="expansion_hypothesis",
            entity_type="customer",
            entity_id=str(customer.id),
            title="Growth hypothesis",
            content={"brief": result.text, "items": payload},
            source_fingerprint=source,
            provider=result.provider,
            is_mock=result.is_mock,
        )
        text = result.text
    else:
        try:
            text = json.loads(reused.content_json).get("brief") or reused.content_json
        except json.JSONDecodeError:
            text = reused.content_json
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="customer",
        entity_id=str(customer.id),
        activity_type="expansion",
        title="Expansion identified",
        body=f"{len(recs)} evidence-supported recommendation(s). Amount unknown.",
        actor_type="ai",
    )
    return {"brief": text}


def growth_plan(db: Session, *, tenant_id: UUID, customer: Customer) -> dict:
    recs = db.scalars(
        select(ExpansionRecommendation).where(
            ExpansionRecommendation.tenant_id == tenant_id,
            ExpansionRecommendation.customer_id == customer.id,
            ExpansionRecommendation.deleted_at.is_(None),
        )
    ).all()
    cells = db.scalars(
        select(WhitespaceCell).where(WhitespaceCell.tenant_id == tenant_id, WhitespaceCell.account_id == customer.account_id)
    ).all()
    return {
        "current_products": len({row.product_id for row in recs if row.product_id}),
        "current_revenue": str(customer.arr) if customer.arr else None,
        "success": customer.lifecycle_state,
        "whitespace": len(cells),
        "expansion_opportunities": [{"id": str(row.id), "title": row.title, "kind": row.kind, "amount": None} for row in recs],
        "recommended_actions": [row.title for row in recs[:5]],
    }


def mint_opportunity(db: Session, *, tenant_id: UUID, actor_id: UUID, recommendation_id: UUID) -> Opportunity | None:
    rec = db.scalar(
        select(ExpansionRecommendation).where(
            ExpansionRecommendation.tenant_id == tenant_id,
            ExpansionRecommendation.id == recommendation_id,
            ExpansionRecommendation.deleted_at.is_(None),
        )
    )
    if rec is None:
        return None
    if rec.opportunity_id:
        return db.get(Opportunity, rec.opportunity_id)
    opp = Opportunity(
        tenant_id=tenant_id,
        created_by=actor_id,
        account_id=rec.account_id,
        name=rec.title,
        stage="qualification",
        amount=rec.amount or 0,
        probability=10,
        next_step="Validate expansion hypothesis with the customer.",
        owner_id=None,
    )
    db.add(opp)
    db.flush()
    rec.opportunity_id = opp.id
    rec.status = "opportunity"
    from app.services.ml.history import record_entity_field, record_feedback

    record_entity_field(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="expansion_recommendation",
        entity_id=str(rec.id),
        field_name="status",
        old_value="open",
        new_value="opportunity",
    )
    record_feedback(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        recommendation_id=rec.id,
        action="accepted",
        entity_id=str(rec.customer_id),
        note="Opportunity minted after approval",
    )
    return opp


def queue_opportunity_approval(db: Session, *, tenant_id: UUID, actor_id: UUID, rec: ExpansionRecommendation) -> None:
    key = f"expansion.opportunity:{rec.id}"
    existing = db.scalar(select(AIApproval).where(AIApproval.tenant_id == tenant_id, AIApproval.idempotency_key == key, AIApproval.deleted_at.is_(None)))
    if existing is not None:
        return
    db.add(
        AIApproval(
            tenant_id=tenant_id,
            created_by=actor_id,
            action_level=2,
            action_type="expansion.opportunity.create",
            title=f"Create expansion opportunity: {rec.title}",
            payload_json=json.dumps(
                {
                    "recommendation_id": str(rec.id),
                    "customer_id": str(rec.customer_id),
                    "why": rec.reason,
                    "evidence": rec.evidence_json,
                    "risk": "Creates a commercial opportunity. Amount is null unless known.",
                    "expected_outcome": "Human-approved CRM opportunity.",
                    "amount": None,
                }
            ),
            status="pending",
            entity_type="customer",
            entity_id=str(rec.customer_id),
            idempotency_key=key,
        )
    )
