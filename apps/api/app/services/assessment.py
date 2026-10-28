"""Lead assessment decisions.

Coverage counts known facts. Confidence describes provenance. Neither is a
conversion probability. A grant does not create consent or eligibility.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment import AssessmentDecision, AssessmentEvidence
from app.models.autonomy import AutopilotSettings
from app.models.crm import ICP, Account, Contact, Lead, Opportunity
from app.models.execution import JourneyLink
from app.models.identity import DomainEvent
from app.services.audit import emit_event

RULES_VERSION = "heuristics-v2"
OBSERVATION_WINDOW_DAYS = 90
REQUIRED_FACETS = ("industry", "employees", "geography", "persona", "business_need")
FACT_CLASSES = {"unknown", "self_reported", "observed", "inferred", "verified"}
INBOUND_SOURCES = {"inbound", "public_form", "website", "event", "manual", "meta_lead_form"}
FREE_MAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"}
MEETING_MARKERS = (
    "can we meet",
    "could we meet",
    "let's meet",
    "lets meet",
    "schedule a call",
    "schedule a meeting",
    "book a call",
    "book a meeting",
    "discovery meeting",
    "discovery call",
)
DEFAULT_SALES_RULES = {
    "business_need": "required",
    "agreed_next_step": "required",
    "authority": "off",
    "timing": "off",
    "budget": "off",
    "company_fit": "required_verified",
    "accept_self_reported_size": False,
}


@dataclass(frozen=True)
class Fact:
    facet: str
    fact_class: str
    value: str = ""
    relation: str = "unknown"
    source: str = "profile"
    excerpt: str = ""

    def as_dict(self) -> dict:
        return {
            "facet": self.facet,
            "fact_class": self.fact_class,
            "value": self.value,
            "relation": self.relation,
            "source": self.source,
            "excerpt": self.excerpt,
        }


def sales_rules_from_settings(settings: AutopilotSettings | None) -> dict:
    raw = getattr(settings, "sales_rules_json", "") if settings is not None else ""
    return sales_rules_from_json(raw or "")


def sales_rules_from_json(raw: str) -> dict:
    parsed: dict = {}
    if raw.strip():
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            parsed = loaded
    merged = dict(DEFAULT_SALES_RULES)
    for key in DEFAULT_SALES_RULES:
        if key in parsed:
            merged[key] = parsed[key]
    merged["accept_self_reported_size"] = bool(merged["accept_self_reported_size"])
    return merged


def meeting_requested_in_text(text: str) -> bool:
    folded = text.casefold()
    return any(marker in folded for marker in MEETING_MARKERS)


def _listed(value: str) -> list[str]:
    return [part.strip().casefold() for part in (value or "").replace(";", ",").split(",") if part.strip()]


def _fact(facet: str, fact_class: str, value: str = "", relation: str = "unknown", source: str = "profile", excerpt: str = "") -> Fact:
    if fact_class not in FACT_CLASSES:
        fact_class = "unknown"
    return Fact(facet=facet, fact_class=fact_class, value=value, relation=relation, source=source, excerpt=excerpt)


def derive_facts(
    lead: Lead,
    account: Account | None,
    icp: ICP | None,
    *,
    overrides: list[Fact] | None = None,
) -> list[Fact]:
    by_facet = {fact.facet: fact for fact in _profile_facts(lead, account, icp)}
    for fact in overrides or []:
        by_facet[fact.facet] = fact
    return [by_facet[name] for name in (*REQUIRED_FACETS, "agreed_next_step", "authority", "timing", "budget") if name in by_facet]


def _profile_facts(lead: Lead, account: Account | None, icp: ICP | None) -> list[Fact]:
    industry_value = (account.industry if account is not None else "").strip()
    industries = _listed(icp.industries) if icp is not None else []
    if not industry_value:
        industry = _fact("industry", "unknown")
    else:
        relation = "unknown"
        if industries:
            relation = "match" if industry_value.casefold() in industries else "mismatch"
        industry = _fact("industry", "self_reported", industry_value, relation, excerpt=industry_value)

    employees_value = account.employee_count if account is not None else None
    if employees_value is None:
        employees = _fact("employees", "unknown")
    else:
        relation = "unknown"
        if icp is not None and (icp.min_employees is not None or icp.max_employees is not None):
            low = icp.min_employees if icp.min_employees is not None else 0
            high = icp.max_employees if icp.max_employees is not None else 10**9
            relation = "inside_range" if low <= employees_value <= high else "outside_range"
        employees = _fact("employees", "self_reported", str(employees_value), relation, excerpt=str(employees_value))

    country = (account.hq_country if account is not None else "").strip()
    geography = _fact("geography", "unknown" if not country else "self_reported", country, "present" if country else "unknown", excerpt=country)

    title = (lead.title or "").strip()
    persona = _fact("persona", "unknown" if not title else "self_reported", title, "present" if title else "unknown", excerpt=title)
    business_need = _fact("business_need", "unknown")
    next_step = _fact("agreed_next_step", "unknown")
    return [
        industry,
        employees,
        geography,
        persona,
        business_need,
        next_step,
        _fact("authority", "unknown"),
        _fact("timing", "unknown"),
        _fact("budget", "unknown"),
    ]


def _known(fact: Fact) -> bool:
    return fact.fact_class != "unknown"


def _verified_present(fact: Fact) -> bool:
    return fact.fact_class == "verified" and fact.relation in {"present", "match", "inside_range"}


def _size_satisfies(fact: Fact, rules: dict) -> bool:
    if fact.relation != "inside_range":
        return False
    if fact.fact_class == "verified":
        return True
    return bool(rules.get("accept_self_reported_size")) and fact.fact_class == "self_reported"


def _company_fit(facts: dict[str, Fact], rules: dict) -> bool:
    mode = str(rules.get("company_fit") or "off")
    if mode == "off":
        return True
    industry = facts["industry"]
    employees = facts["employees"]
    industry_ok = industry.relation == "match" and industry.fact_class == "verified"
    return industry_ok and _size_satisfies(employees, rules)


def _requirement_met(rule: str, fact: Fact, *, rules: dict, facet: str) -> bool:
    if rule == "off":
        return True
    if facet == "employees":
        return _size_satisfies(fact, rules)
    return _verified_present(fact)


def decide_assessment(
    *,
    facts: list[Fact],
    consent_email: bool,
    opt_out: bool,
    email: str,
    company_name: str,
    source: str,
    notes: str,
    meeting_requested: bool,
    rules: dict | None = None,
    has_account: bool = False,
    grant_id: str = "",
) -> dict:
    """Return the four decisions. grant_id is ignored on purpose."""
    _ = grant_id
    active_rules = sales_rules_from_json("") if rules is None else rules
    by_facet = {fact.facet: fact for fact in facts}
    for facet in (*REQUIRED_FACETS, "agreed_next_step", "authority", "timing", "budget"):
        by_facet.setdefault(facet, _fact(facet, "unknown"))
    ordered = [by_facet[facet] for facet in (*REQUIRED_FACETS, "agreed_next_step", "authority", "timing", "budget")]
    coverage_known = sum(1 for facet in REQUIRED_FACETS if _known(by_facet[facet]))
    if any(fact.relation == "contested" for fact in ordered):
        confidence = "contested"
    elif coverage_known == 0:
        confidence = "none"
    elif all(fact.fact_class == "verified" for fact in ordered if _known(fact)):
        confidence = "high"
    else:
        confidence = "limited"

    if opt_out:
        identity = "suppressed"
    elif not (email or company_name):
        identity = "invalid"
    else:
        identity = "resolved"

    industry = by_facet["industry"]
    employees = by_facet["employees"]
    not_a_fit = (industry.fact_class == "verified" and industry.relation == "mismatch") or (
        employees.fact_class == "verified" and employees.relation == "outside_range"
    )
    enquiry = source in INBOUND_SOURCES or (source != "ai_discovery" and bool(notes.strip()))
    asked = meeting_requested or meeting_requested_in_text(notes)
    eligible_identity = identity == "resolved" and not not_a_fit
    response_eligible = bool(consent_email and not opt_out and eligible_identity and enquiry)
    meeting_eligible = bool(asked and not opt_out and eligible_identity and (consent_email or meeting_requested))

    sales_qualified = False
    if eligible_identity and not opt_out:
        gates = {
            "business_need": by_facet["business_need"],
            "agreed_next_step": by_facet["agreed_next_step"],
            "authority": by_facet["authority"],
            "timing": by_facet["timing"],
            "budget": by_facet["budget"],
        }
        sales_qualified = all(
            _requirement_met(str(active_rules.get(name) or "off"), fact, rules=active_rules, facet=name) for name, fact in gates.items()
        ) and _company_fit(by_facet, active_rules)
    known_facets = {name for name in ("industry", "employees", "persona", "business_need") if _known(by_facet[name])}
    prospect_identified = bool(company_name.strip() or known_facets)
    outbound_eligible = bool(consent_email and not opt_out and eligible_identity and not enquiry and prospect_identified)

    if identity == "suppressed" or not_a_fit:
        next_action = "stop"
    elif sales_qualified and not has_account and not company_name:
        next_action = "handoff_waiting"
    elif sales_qualified and not has_account:
        next_action = "handoff_waiting"
    elif sales_qualified:
        next_action = "handoff_opportunity"
    elif meeting_eligible:
        next_action = "book_discovery_meeting"
    elif outbound_eligible:
        next_action = "prepare_outreach"
    elif response_eligible:
        next_action = "acknowledge"
    else:
        next_action = "wait"

    reasons = [
        f"identity={identity}",
        f"coverage={coverage_known}/{len(REQUIRED_FACETS)}",
        f"confidence={confidence}",
    ]
    if not_a_fit:
        reasons.append("verified_not_a_fit")
    if response_eligible:
        reasons.append("response_eligible")
    if meeting_eligible:
        reasons.append("meeting_eligible")
    if outbound_eligible:
        reasons.append("outbound_eligible")
    if sales_qualified:
        reasons.append("sales_qualified")
    return {
        "identity": identity,
        "facts": [fact.as_dict() for fact in ordered],
        "coverage_known": coverage_known,
        "coverage_required": len(REQUIRED_FACETS),
        "confidence": confidence,
        "response_eligible": response_eligible,
        "outbound_eligible": outbound_eligible,
        "meeting_eligible": meeting_eligible,
        "sales_qualified": sales_qualified,
        "not_a_fit": not_a_fit,
        "next_action": next_action,
        "rules_version": RULES_VERSION,
        "reasons": reasons,
        "observation_window_days": OBSERVATION_WINDOW_DAYS,
    }


def _content_hash(fact: Fact) -> str:
    material = f"{fact.facet}|{fact.fact_class}|{fact.relation}|{fact.value}|{fact.excerpt}".strip().casefold()
    return hashlib.sha256(material.encode()).hexdigest()


def _polarity(fact: Fact) -> str:
    if fact.relation in {"match", "inside_range", "present"}:
        return "positive"
    if fact.relation in {"mismatch", "outside_range"}:
        return "negative"
    return "neutral"


def _default_icp(db: Session, tenant_id: UUID) -> ICP | None:
    return db.scalar(
        select(ICP).where(ICP.tenant_id == tenant_id, ICP.is_default.is_(True), ICP.deleted_at.is_(None))
    )


def assess_and_store(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    settings: AutopilotSettings | None = None,
    meeting_requested: bool = False,
    overrides: list[Fact] | None = None,
    correlation_id: str = "",
    grant_id: str = "",
) -> dict:
    account = db.get(Account, lead.account_id) if lead.account_id else None
    contact = db.get(Contact, lead.contact_id) if lead.contact_id else None
    opt_out = bool(lead.opt_out or (contact.opt_out if contact is not None else False))
    bound_icp = db.get(ICP, lead.icp_id) if lead.icp_id else None
    if bound_icp is None or bound_icp.tenant_id != tenant_id or bound_icp.deleted_at is not None:
        bound_icp = _default_icp(db, tenant_id) if lead.icp_id is None else None
    facts = derive_facts(lead, account, bound_icp, overrides=overrides)
    decision = decide_assessment(
        facts=facts,
        consent_email=bool(lead.consent_email),
        opt_out=opt_out,
        email=lead.email or "",
        company_name=lead.company_name or "",
        source=lead.source or "",
        notes=lead.notes or "",
        meeting_requested=meeting_requested,
        rules=sales_rules_from_settings(settings),
        has_account=account is not None,
        grant_id=grant_id,
    )
    evidence_ids = _store_evidence(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, facts=facts)
    payload = dict(decision)
    payload.pop("observation_window_days", None)
    row = AssessmentDecision(
        tenant_id=tenant_id,
        created_by=actor_id,
        lead_id=lead.id,
        identity=decision["identity"],
        fit_json=json.dumps(payload),
        coverage_known=decision["coverage_known"],
        coverage_required=decision["coverage_required"],
        confidence=decision["confidence"],
        response_eligible=decision["response_eligible"],
        outbound_eligible=decision["outbound_eligible"],
        meeting_eligible=decision["meeting_eligible"],
        sales_qualified=decision["sales_qualified"],
        not_a_fit=decision["not_a_fit"],
        next_action=decision["next_action"],
        rules_version=RULES_VERSION,
    )
    db.add(row)
    db.flush()
    decision["decision_id"] = str(row.id)
    decision["evidence_ids"] = evidence_ids
    if decision["meeting_eligible"] and not _event_exists(db, tenant_id, "meeting.eligible", str(lead.id)):
        emit_event(
            db,
            tenant_id=tenant_id,
            event_type="meeting.eligible",
            entity_type="lead",
            entity_id=str(lead.id),
            payload={"decision_id": str(row.id), "next_action": decision["next_action"]},
            correlation_id=correlation_id,
        )
    return decision


def _event_exists(db: Session, tenant_id: UUID, event_type: str, entity_id: str) -> bool:
    return (
        db.scalar(
            select(DomainEvent.id).where(
                DomainEvent.tenant_id == tenant_id,
                DomainEvent.event_type == event_type,
                DomainEvent.entity_id == entity_id,
            )
        )
        is not None
    )


def _store_evidence(db: Session, *, tenant_id: UUID, actor_id: UUID, lead: Lead, facts: list[Fact]) -> list[str]:
    person_id = str(lead.contact_id or lead.id)
    ids: list[str] = []
    now = datetime.now(UTC)
    for fact in facts:
        if fact.fact_class == "unknown" and not fact.excerpt:
            continue
        digest = _content_hash(fact)
        existing = db.scalar(
            select(AssessmentEvidence).where(
                AssessmentEvidence.tenant_id == tenant_id,
                AssessmentEvidence.person_id == person_id,
                AssessmentEvidence.kind == fact.facet,
                AssessmentEvidence.source == fact.source,
                AssessmentEvidence.content_hash == digest,
                AssessmentEvidence.deleted_at.is_(None),
            )
        )
        if existing is None:
            existing = AssessmentEvidence(
                tenant_id=tenant_id,
                created_by=actor_id,
                person_id=person_id,
                kind=fact.facet,
                source=fact.source,
                content_hash=digest,
                polarity=_polarity(fact),
                observed_at=now,
                excerpt=(fact.excerpt or fact.value)[:1000],
            )
            db.add(existing)
            db.flush()
        ids.append(str(existing.id))
    return ids


def latest_decision(db: Session, *, tenant_id: UUID, lead_id: UUID) -> AssessmentDecision | None:
    return db.scalar(
        select(AssessmentDecision)
        .where(
            AssessmentDecision.tenant_id == tenant_id,
            AssessmentDecision.lead_id == lead_id,
            AssessmentDecision.deleted_at.is_(None),
        )
        .order_by(AssessmentDecision.created_at.desc(), AssessmentDecision.id.desc())
    )


def handoff_sales_opportunity(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    correlation_id: str = "",
    decision_id: str = "",
) -> Opportunity | None:
    """Create one opportunity for a sales-qualified lead. Repeat calls return it."""
    decision = db.get(AssessmentDecision, UUID(decision_id)) if decision_id else None
    if decision is None or decision.tenant_id != tenant_id or decision.lead_id != lead.id:
        decision = latest_decision(db, tenant_id=tenant_id, lead_id=lead.id)
    if decision is None or not decision.sales_qualified:
        return None
    if lead.account_id is None:
        return None
    journey_key = f"lead:{lead.id}"
    existing = db.scalar(
        select(JourneyLink).where(
            JourneyLink.tenant_id == tenant_id,
            JourneyLink.journey_key == journey_key,
            JourneyLink.entity_type == "opportunity",
            JourneyLink.role == "sales_handoff",
            JourneyLink.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return db.get(Opportunity, UUID(existing.entity_id))
    opportunity = Opportunity(
        tenant_id=tenant_id,
        created_by=actor_id,
        account_id=lead.account_id,
        name=f"{lead.company_name or lead.email or 'Lead'} enquiry",
        stage="qualification",
        amount=0,
        probability=10,
        next_step="Discovery agreed",
        owner_id=lead.owner_id,
        campaign_id=lead.campaign_id,
        ad_id=lead.ad_id or "",
        utm_source=lead.utm_source or "",
        utm_medium=lead.utm_medium or "",
        utm_campaign=lead.utm_campaign or "",
    )
    db.add(opportunity)
    db.flush()
    db.add(
        JourneyLink(
            tenant_id=tenant_id,
            created_by=actor_id,
            journey_key=journey_key,
            entity_type="lead",
            entity_id=str(lead.id),
            role="source",
        )
    )
    db.add(
        JourneyLink(
            tenant_id=tenant_id,
            created_by=actor_id,
            journey_key=journey_key,
            entity_type="opportunity",
            entity_id=str(opportunity.id),
            role="sales_handoff",
        )
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="opportunity.created",
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        payload={"lead_id": str(lead.id), "source": "sales_qualification"},
        correlation_id=correlation_id,
    )
    db.flush()
    return opportunity
