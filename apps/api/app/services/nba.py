from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Lead, NextBestAction, Opportunity


def generate_for_opportunity(db: Session, tenant_id: UUID, opportunity: Opportunity, actor_id: UUID) -> NextBestAction:
    if not opportunity.next_step:
        action = "Set a concrete next step and meeting date"
        reason = "Opportunity has no next step recorded"
        priority = "high"
    elif opportunity.stage in {"proposal", "negotiation"}:
        action = "Confirm economic buyer and commercial approval path"
        reason = f"Late-stage deal in {opportunity.stage} needs buying committee coverage"
        priority = "high"
    else:
        action = "Advance discovery with a written summary to the champion"
        reason = f"Stage {opportunity.stage} is missing documented qualification depth"
        priority = "medium"
    row = NextBestAction(
        tenant_id=tenant_id,
        created_by=actor_id,
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        action=action,
        reason=reason,
        priority=priority,
        confidence=78,
        expected_impact="Reduce stall risk",
        owner_id=opportunity.owner_id,
    )
    db.add(row)
    return row


def generate_for_lead(db: Session, tenant_id: UUID, lead: Lead, actor_id: UUID) -> NextBestAction:
    latest = db.scalar(
        select(NextBestAction)
        .where(
            NextBestAction.tenant_id == tenant_id,
            NextBestAction.entity_type == "lead",
            NextBestAction.entity_id == str(lead.id),
        )
        .limit(1)
    )
    _ = latest
    if lead.opt_out:
        action = "Do not contact — honor suppression"
        reason = "Lead is opted out"
        priority = "high"
    elif not lead.consent_email:
        action = "Use consented channel only; log research internally"
        reason = "No email consent on file"
        priority = "medium"
    else:
        action = "Draft a personalized first-touch email for approval"
        reason = "Lead is eligible for drafted outreach"
        priority = "medium"
    row = NextBestAction(
        tenant_id=tenant_id,
        created_by=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        action=action,
        reason=reason,
        priority=priority,
        confidence=74,
        expected_impact="Move lead to conversation",
    )
    db.add(row)
    return row
