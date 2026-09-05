import json
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.lifecycle import Campaign
from app.providers.ads import get_ads_provider
from app.services.audit import write_audit
from app.services.query import get_owned

PAID_CHANNELS = {"linkedin", "instagram"}


def queue_campaign_launch(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    campaign: Campaign,
    correlation_id: str = "",
) -> AIApproval:
    if campaign.channel not in PAID_CHANNELS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Launch is only for LinkedIn or Instagram campaigns.",
        )
    if campaign.status == "launched":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campaign is already launched.")
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="ads.spend",
        title=f"Launch {campaign.channel} campaign {campaign.name}",
        payload_json=json.dumps(
            {
                "campaign_id": str(campaign.id),
                "channel": campaign.channel,
                "budget": str(campaign.budget),
            }
        ),
        status="pending",
    )
    db.add(approval)
    campaign.status = "pending_approval"
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="campaign.launch_requested",
        entity_type="campaign",
        entity_id=str(campaign.id),
        after={"status": campaign.status},
        correlation_id=correlation_id,
    )
    db.flush()
    return approval


def execute_ads_spend(db: Session, *, tenant_id: UUID, approval: AIApproval) -> str:
    payload = json.loads(approval.payload_json or "{}")
    campaign_id = payload.get("campaign_id")
    if not campaign_id:
        return "No campaign_id on this approval. Spend was not invented."
    campaign = get_owned(db, Campaign, tenant_id, UUID(campaign_id))
    provider = get_ads_provider(campaign.channel)
    health = provider.health()
    result = provider.create_campaign(name=campaign.name, objective=campaign.objective, budget=Decimal(str(campaign.budget)))
    if result.ok:
        campaign.status = "launched"
        if result.external_id:
            suffix = f" provider_campaign_id={result.external_id}"
            campaign.notes = (campaign.notes + suffix).strip()
        spend = provider.get_spend(external_id=result.external_id)
        if spend.amount is not None:
            campaign.spent = spend.amount
        return f"Provider {result.provider} launched the campaign. Spend remains ledger-only until the network returns a figure."
    campaign.status = "draft"
    return (
        f"{result.reason or health.reason} "
        f"Campaign {campaign.name} was not launched. No CTR or spend was invented."
    )
