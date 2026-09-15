import json
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.models.ai import AIApproval
from app.models.crm import Account, Customer, Lead, Renewal
from app.models.lifecycle import AdvocacyAsset, HealthScore, Referral
from app.models.post_sale import CustomerRisk
from app.services.ai_artifacts import fingerprint, reuse_or_none, upsert_artifact
from app.services.audit import emit_event
from app.services.crm import add_activity

ADVOCACY_TYPES = ["testimonial", "case_study", "reference", "speaker", "review", "referral"]


def eligibility(db: Session, *, tenant_id: UUID, customer: Customer, settings) -> dict:
    health = db.scalar(select(HealthScore).where(HealthScore.tenant_id == tenant_id, HealthScore.customer_id == customer.id, HealthScore.deleted_at.is_(None)))
    risks = db.scalars(
        select(CustomerRisk).where(
            CustomerRisk.tenant_id == tenant_id,
            CustomerRisk.customer_id == customer.id,
            CustomerRisk.status == "open",
            CustomerRisk.severity == "high",
        )
    ).all()
    renewal = db.scalar(select(Renewal).where(Renewal.tenant_id == tenant_id, Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None)))
    score = 0
    evidence: dict = {}
    if health and health.total >= 70:
        score += 30
        evidence["health"] = health.total
    if customer.lifecycle_state in {"ACTIVE", "RENEWED", "EXPANSION"}:
        score += 20
        evidence["lifecycle"] = customer.lifecycle_state
    if customer.onboarding_completed_at:
        score += 15
        evidence["onboarding_complete"] = True
    if not risks:
        score += 15
        evidence["no_critical_risks"] = True
    else:
        evidence["critical_risks"] = [row.risk_type for row in risks]
    if renewal and renewal.status in {"renewed", "completed"}:
        score += 10
        evidence["renewed"] = True
    if customer.health_trend == "improving":
        score += 10
    tenure_days = (date.today() - customer.created_at.date()).days if customer.created_at else 0
    if tenure_days >= 90:
        score += 10
        evidence["tenure_days"] = tenure_days
    from app.services.support_ingest import customer_support_metrics

    metrics = customer_support_metrics(db, tenant_id, customer.id)
    coverage = int(getattr(health, "health_data_coverage", 0) or 0) if health else 0
    min_coverage = int(getattr(settings, "minimum_health_coverage", 40) or 0)
    if metrics["open_critical"]:
        evidence["critical_support"] = metrics["open_critical"]
        score = min(score, 40)
    live_policy = bool(
        getattr(settings, "usage_live_enabled", False)
        or getattr(settings, "support_live_enabled", False)
        or getattr(settings, "finance_live_enabled", False)
    )
    coverage_ok = coverage >= min_coverage if (live_policy or coverage > 0) else True
    if not coverage_ok:
        evidence["coverage"] = coverage
        score = min(score, 45)
    eligible = (
        score >= settings.minimum_advocacy_score
        and not risks
        and health is not None
        and health.total >= 70
        and not metrics["open_critical"]
        and coverage_ok
    )
    return {"score": score, "eligible": eligible, "evidence": evidence, "version": "advocacy-rules-v2", "blocked": bool(metrics["open_critical"])}


def recommend_type(result: dict) -> str:
    if result["evidence"].get("renewed"):
        return "case_study"
    if result["score"] >= 80:
        return "reference"
    return "testimonial"


def evaluate_advocacy(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, settings) -> AdvocacyAsset | None:
    result = eligibility(db, tenant_id=tenant_id, customer=customer, settings=settings)
    if not result["eligible"]:
        return None
    kind = recommend_type(result)
    period = date.today().strftime("%Y-%m")
    existing = db.scalar(
        select(AdvocacyAsset).where(
            AdvocacyAsset.tenant_id == tenant_id,
            AdvocacyAsset.customer_id == customer.id,
            AdvocacyAsset.advocacy_type == kind,
            AdvocacyAsset.deleted_at.is_(None),
        )
    )
    if existing is not None:
        existing.eligibility_score = result["score"]
        existing.evidence_json = json.dumps(result["evidence"], default=str)
        return existing
    asset = AdvocacyAsset(
        tenant_id=tenant_id,
        created_by=actor_id,
        account_id=customer.account_id,
        customer_id=customer.id,
        kind=kind,
        advocacy_type=kind,
        readiness=result["score"],
        eligibility_score=result["score"],
        status="identified",
        notes="advocacy-rules-v2. Critical support or thin coverage blocks advocacy.",
        ruleset_version="advocacy-rules-v2",
        evidence_json=json.dumps(result["evidence"], default=str),
        quote=None,
    )
    db.add(asset)
    db.flush()
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="advocacy.eligible",
        entity_type="customer",
        entity_id=str(customer.id),
        payload={"asset_id": str(asset.id), "type": kind, "period": period, "score": result["score"]},
    )
    from app.services.nba import generate_for_advocacy

    run_advocacy_agent(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer, asset=asset)
    generate_for_advocacy(db, tenant_id, asset, actor_id)
    return asset


def run_advocacy_agent(db: Session, *, tenant_id: UUID, actor_id: UUID, customer: Customer, asset: AdvocacyAsset) -> dict:
    evidence = {"type": asset.advocacy_type, "score": asset.eligibility_score, "evidence": asset.evidence_json, "quote": None}
    source = fingerprint(evidence)
    reused = reuse_or_none(db, tenant_id=tenant_id, kind="advocacy", entity_type="customer", entity_id=str(asset.id), source_fingerprint=source)
    if reused is None:
        llm = get_llm_provider()
        result = llm.complete(
            json.dumps(evidence, default=str),
            system=(
                "You are AdvocacyAgent. Prepare evidence, recommend advocacy type, draft a request, "
                "and a case-study outline. Never invent quotes. quote stays null until approved. No tools."
            ),
        )
        reused = upsert_artifact(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            kind="advocacy",
            entity_type="customer",
            entity_id=str(asset.id),
            title=f"Advocacy {asset.advocacy_type}",
            content={"brief": result.text, "quote": None},
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
    key = f"advocacy.request:{customer.id}:{asset.advocacy_type}"
    existing = db.scalar(select(AIApproval).where(AIApproval.tenant_id == tenant_id, AIApproval.idempotency_key == key, AIApproval.deleted_at.is_(None)))
    if existing is None:
        db.add(
            AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="advocacy.request.send",
                title=f"Request {asset.advocacy_type.replace('_', ' ')}",
                payload_json=json.dumps(
                    {
                        "customer_id": str(customer.id),
                        "asset_id": str(asset.id),
                        "why": f"advocacy-rules-v1 score {asset.eligibility_score}.",
                        "evidence": asset.evidence_json,
                        "risk": "External customer ask.",
                        "expected_outcome": "Human-approved advocacy request.",
                        "body": text[:2000],
                        "subject": "Would you share your experience?",
                        "quote": None,
                    }
                ),
                status="pending",
                entity_type="customer",
                entity_id=str(customer.id),
                idempotency_key=key,
            )
        )
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="customer",
        entity_id=str(customer.id),
        activity_type="advocacy",
        title="Advocacy candidate identified",
        body=f"{asset.advocacy_type} · score {asset.eligibility_score}. Quote is null.",
        actor_type="ai",
    )
    return {"brief": text}


def ingest_referral(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    referral: Referral,
) -> Lead | None:
    if referral.converted_lead_id:
        return db.get(Lead, referral.converted_lead_id)
    account = db.get(Account, referral.referrer_account_id)
    lead = Lead(
        tenant_id=tenant_id,
        created_by=actor_id,
        email=referral.email,
        first_name=(referral.referred_name.split(" ") or ["Referral"])[0],
        last_name=" ".join(referral.referred_name.split(" ")[1:]) or "Referral",
        company_name=account.name if account else "",
        account_id=None,
        source="referral",
        consent_email=False,
        status="new",
    )
    db.add(lead)
    db.flush()
    referral.converted_lead_id = lead.id
    referral.status = "routed"
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="referral.received",
        entity_type="lead",
        entity_id=str(lead.id),
        payload={"referral_id": str(referral.id), "source": "referral", "consent_email": False},
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="lead.created",
        entity_type="lead",
        entity_id=str(lead.id),
        payload={"source": "referral"},
    )
    return lead
