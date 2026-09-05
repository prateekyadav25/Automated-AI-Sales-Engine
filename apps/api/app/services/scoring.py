from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import ICP, Account, Lead, LeadScore
from app.services.audit import emit_event

PERSONA_TITLES = {
    "ceo": 10,
    "cio": 10,
    "cto": 10,
    "cfo": 9,
    "ciso": 9,
    "chief": 9,
    "head": 8,
    "director": 7,
    "vp": 8,
    "vice president": 8,
}


def _persona_points(title: str) -> tuple[int, str]:
    lowered = title.lower()
    for key, points in PERSONA_TITLES.items():
        if key in lowered:
            return points, f"Persona match on '{key}'"
    return 3, "Persona is not an executive buyer"


def score_lead(db: Session, lead: Lead, *, emit: bool = True, correlation_id: str = "") -> LeadScore:
    account = db.get(Account, lead.account_id) if lead.account_id else None
    icp = db.scalar(
        select(ICP).where(ICP.tenant_id == lead.tenant_id, ICP.deleted_at.is_(None), ICP.is_default.is_(True))
    )
    reasons: list[str] = []

    icp_fit = 8
    if icp and account:
        industries = [p.strip().lower() for p in icp.industries.split(",") if p.strip()]
        if account.industry.lower() in industries:
            icp_fit = 25
            reasons.append(f"Industry '{account.industry}' matches default ICP")
        else:
            icp_fit = 10
            reasons.append("Industry does not match default ICP")
        if icp.min_employees and account.employee_count and account.employee_count >= icp.min_employees:
            icp_fit = min(25, icp_fit + 4)
    else:
        reasons.append("No default ICP or account linked; conservative ICP fit")

    intent = min(20, max(0, int(lead.intent_score * 20 / 100)))
    reasons.append(f"Intent component from stored intent_score={lead.intent_score}")

    engagement = min(20, max(0, int(lead.engagement_score * 20 / 100)))
    reasons.append(f"Engagement component from stored engagement_score={lead.engagement_score}")

    persona, persona_reason = _persona_points(lead.title)
    reasons.append(persona_reason)

    company_potential = 5
    if account and account.employee_count:
        if account.employee_count >= 1000:
            company_potential = 10
        elif account.employee_count >= 200:
            company_potential = 8
        else:
            company_potential = 6
        reasons.append(f"Company potential from employee_count={account.employee_count}")
    else:
        reasons.append("Company potential limited without firmographics")

    buying_trigger = 10 if lead.has_buying_trigger else 2
    reasons.append("Buying trigger present" if lead.has_buying_trigger else "No buying trigger recorded")

    created = lead.created_at or datetime.now(UTC)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - created).days
    timing = 5 if age_days <= 14 else 3 if age_days <= 45 else 1
    reasons.append(f"Timing from lead age {age_days} days")

    total = icp_fit + intent + engagement + persona + company_potential + buying_trigger + timing
    row = LeadScore(
        tenant_id=lead.tenant_id,
        created_by=lead.updated_by,
        lead_id=lead.id,
        total=total,
        icp_fit=icp_fit,
        intent=intent,
        engagement=engagement,
        persona=persona,
        company_potential=company_potential,
        buying_trigger=buying_trigger,
        timing=timing,
        reasons=" | ".join(reasons),
        version="rules-v1",
        confidence=85 if account and icp else 65,
    )
    db.add(row)
    db.flush()
    if total >= 60 and lead.status == "new":
        lead.status = "working"
    if emit:
        emit_event(
            db,
            tenant_id=lead.tenant_id,
            event_type="lead.scored",
            entity_type="lead",
            entity_id=str(lead.id),
            payload={"total": total, "version": "rules-v1"},
            correlation_id=correlation_id,
        )
    return row
