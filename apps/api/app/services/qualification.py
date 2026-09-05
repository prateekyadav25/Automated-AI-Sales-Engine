from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.autonomy import AutopilotSettings
from app.models.crm import Lead, LeadScore
from app.services.audit import emit_event
from app.services.crm import add_activity


def latest_score(db: Session, lead: Lead) -> LeadScore | None:
    return db.scalar(
        select(LeadScore)
        .where(LeadScore.lead_id == lead.id, LeadScore.deleted_at.is_(None))
        .order_by(LeadScore.created_at.desc())
    )


def qualify_lead(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    settings: AutopilotSettings,
    correlation_id: str = "",
) -> dict:
    score = latest_score(db, lead)
    reasons: list[str] = []
    missing: list[str] = []
    total = score.total if score else 0
    icp_fit = score.icp_fit if score else 0
    if score is None:
        missing.append("score")
        reasons.append("No persisted rules-v1 score")
    elif total < settings.minimum_lead_score:
        reasons.append(f"Score {total} is below minimum {settings.minimum_lead_score}")
    else:
        reasons.append(f"Score {total} meets minimum {settings.minimum_lead_score}")
    if not lead.email and not lead.company_name:
        missing.append("identity")
        reasons.append("Lead has no email or company")
    if lead.intent_score < settings.minimum_intent_score:
        reasons.append(f"Intent {lead.intent_score} is below minimum {settings.minimum_intent_score}")
    qualified = not missing and total >= settings.minimum_lead_score and lead.intent_score >= settings.minimum_intent_score
    event_type = "lead.qualified" if qualified else "lead.disqualified"
    if qualified and lead.status == "new":
        lead.status = "working"
    payload = {
        "qualified": qualified,
        "total": total,
        "icp_fit": icp_fit,
        "reasons": reasons,
        "missing": missing,
        "policy": "rules-v1",
    }
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="qualification",
        title="Lead qualified" if qualified else "Lead not qualified",
        body=" | ".join(reasons),
        actor_type="ai",
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type=event_type,
        entity_type="lead",
        entity_id=str(lead.id),
        payload=payload,
        correlation_id=correlation_id,
    )
    return payload
