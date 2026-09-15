import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.autonomy import AutopilotSettings
from app.models.crm import Contact, Lead
from app.models.funnel import AdAudience, AdCreative, CampaignMetricDaily
from app.models.lifecycle import Campaign
from app.providers.ads import AdsMetrics, get_ads_provider
from app.services.audit import emit_event, write_audit
from app.services.autopilot_settings import get_or_create_settings
from app.services.consent import email_block_reason
from app.services.idempotency import claim_key
from app.services.provider_metrics import ADS_LAUNCH_FAILURES, ADS_LAUNCHES
from app.services.provider_ops import (
    begin_action,
    block_action,
    confirm_action,
    fail_action,
    is_circuit_open,
    record_provider_result,
)
from app.services.query import get_owned

PAID_CHANNELS = {"linkedin", "instagram"}


def derived_metrics(metrics: AdsMetrics) -> dict[str, Decimal | None]:
    ctr = (Decimal(metrics.clicks) / Decimal(metrics.impressions)) if metrics.clicks is not None and metrics.impressions else None
    cpc = (metrics.spend / Decimal(metrics.clicks)) if metrics.spend is not None and metrics.clicks else None
    cpl = (metrics.spend / Decimal(metrics.conversions)) if metrics.spend is not None and metrics.conversions else None
    return {"ctr": ctr, "cpc": cpc, "cpl": cpl, "roas": None}


def spent_in_window(db: Session, *, tenant_id: UUID, start: datetime) -> Decimal:
    value = db.scalar(
        select(func.coalesce(func.sum(Campaign.spent), 0)).where(
            Campaign.tenant_id == tenant_id,
            Campaign.deleted_at.is_(None),
            Campaign.last_synced_at.is_not(None),
            Campaign.last_synced_at >= start,
        )
    )
    return Decimal(str(value or 0))


def budget_block_reason(db: Session, *, settings: AutopilotSettings, campaign: Campaign) -> str | None:
    budget = Decimal(str(campaign.budget or 0))
    if budget < 0:
        return "Campaign budget is invalid."
    if settings.daily_budget_limit and Decimal(str(settings.daily_budget_limit)) > 0:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        if spent_in_window(db, tenant_id=settings.tenant_id, start=start) + budget > Decimal(str(settings.daily_budget_limit)):
            return "Daily ad budget would be exceeded."
    if settings.monthly_budget_limit and Decimal(str(settings.monthly_budget_limit)) > 0:
        now = datetime.now(UTC)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if spent_in_window(db, tenant_id=settings.tenant_id, start=start) + budget > Decimal(str(settings.monthly_budget_limit)):
            return "Monthly ad budget would be exceeded."
    return None


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
    if campaign.status == "launched" and campaign.external_campaign_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campaign is already launched.")
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    blocked = budget_block_reason(db, settings=settings, campaign=campaign)
    if blocked:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=blocked)
    fresh, _ = claim_key(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        key=f"ads.spend:{campaign.id}",
        workflow="ads",
        entity_id=str(campaign.id),
        action_type="ads.spend",
    )
    if not fresh:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Launch approval already queued for this campaign.")
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
        entity_type="campaign",
        entity_id=str(campaign.id),
        idempotency_key=f"ads.spend:{campaign.id}",
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


def execute_ads_spend(db: Session, *, tenant_id: UUID, actor_id: UUID, approval: AIApproval) -> str:
    payload = json.loads(approval.payload_json or "{}")
    campaign_id = payload.get("campaign_id")
    if not campaign_id:
        return "No campaign_id on this approval. Spend was not invented."
    campaign = get_owned(db, Campaign, tenant_id, UUID(campaign_id))
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    key = f"ads.launch:{tenant_id}:{approval.id}"
    provider_name = "linkedin-ads" if campaign.channel == "linkedin" else "meta-ads"
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="ads.launch",
        idempotency_key=key,
        provider=provider_name,
        approval_id=approval.id,
        entity_type="campaign",
        entity_id=str(campaign.id),
        request_summary=f"channel={campaign.channel} budget={campaign.budget}",
    )
    if action.status == "CONFIRMED" and action.external_id:
        return f"Launch already confirmed as {action.external_id}."
    if action.status == "BLOCKED":
        return action.last_error or "Campaign was not launched. No CTR or spend was invented."
    if campaign.external_campaign_id and campaign.status == "launched":
        confirm_action(action, provider=campaign.provider or provider_name, external_id=campaign.external_campaign_id)
        return f"Campaign already launched as {campaign.external_campaign_id}."
    blocked = budget_block_reason(db, settings=settings, campaign=campaign)
    if blocked:
        block_action(action, reason=blocked)
        campaign.status = "draft"
        return blocked
    if is_circuit_open(db, tenant_id=tenant_id, provider=provider_name):
        block_action(action, reason="Provider circuit is open", failure_class="TRANSIENT")
        campaign.status = "draft"
        return "Blocked by provider. Campaign was not launched."
    provider = get_ads_provider(campaign.channel, db, tenant_id)
    health = provider.health()
    if health.is_mock or not health.connected:
        block_action(action, reason=health.reason, failure_class="CONFIGURATION")
        campaign.status = "draft"
        record_provider_result(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            provider=health.provider,
            action="ads.launch",
            ok=False,
            failure_class="CONFIGURATION",
            error=health.reason,
        )
        ADS_LAUNCH_FAILURES.labels(provider=health.provider[:40]).inc()
        return (
            f"{health.reason} "
            f"Campaign {campaign.name} was not launched. No CTR or spend was invented."
        )
    result = provider.create_campaign(name=campaign.name, objective=campaign.objective, budget=Decimal(str(campaign.budget)))
    record_provider_result(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        provider=result.provider,
        action="ads.launch",
        ok=result.ok and bool(result.external_id),
        failure_class=result.failure_class,
        error=result.reason,
    )
    if result.ok and result.external_id:
        if result.provider_status == "PAUSED":
            activated = provider.activate_campaign(external_id=result.external_id)
            if activated.ok:
                result = activated
        campaign.status = "launched"
        campaign.external_campaign_id = result.external_id
        campaign.provider = result.provider
        campaign.provider_status = result.provider_status or "CREATED"
        campaign.launch_approval_id = approval.id
        confirm_action(action, provider=result.provider, external_id=result.external_id, response_summary="launched")
        emit_event(
            db,
            tenant_id=tenant_id,
            event_type="campaign.launched",
            entity_type="campaign",
            entity_id=str(campaign.id),
            payload={"external_id": result.external_id, "provider": result.provider},
        )
        write_audit(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="campaign.launched",
            entity_type="campaign",
            entity_id=str(campaign.id),
            after={"external_campaign_id": result.external_id, "provider": result.provider},
        )
        ADS_LAUNCHES.labels(provider=result.provider[:40]).inc()
        return f"Provider {result.provider} launched the campaign. Spend remains ledger-only until the network returns a figure."
    campaign.status = "draft"
    fail_action(
        action,
        failure_class=result.failure_class or "PERMANENT",
        error=result.reason,
        retryable=result.failure_class == "TRANSIENT",
    )
    ADS_LAUNCH_FAILURES.labels(provider=result.provider[:40]).inc()
    return (
        f"{result.reason or health.reason} "
        f"Campaign {campaign.name} was not launched. No CTR or spend was invented."
    )


def execute_ads_pause(db: Session, *, tenant_id: UUID, actor_id: UUID, approval: AIApproval) -> str:
    payload = json.loads(approval.payload_json or "{}")
    campaign_id = payload.get("campaign_id")
    if not campaign_id:
        return "No campaign_id on this approval."
    campaign = get_owned(db, Campaign, tenant_id, UUID(campaign_id))
    if not campaign.external_campaign_id:
        return "Campaign has no provider id to pause."
    key = f"ads.pause:{tenant_id}:{approval.id}"
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="ads.pause",
        idempotency_key=key,
        provider=campaign.provider or "ads",
        approval_id=approval.id,
        entity_type="campaign",
        entity_id=str(campaign.id),
    )
    if action.status == "CONFIRMED":
        return "Pause already confirmed."
    provider = get_ads_provider(campaign.channel, db, tenant_id)
    result = provider.pause_campaign(external_id=campaign.external_campaign_id)
    record_provider_result(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        provider=result.provider,
        action="ads.pause",
        ok=result.ok,
        failure_class=result.failure_class,
        error=result.reason,
    )
    if result.ok:
        campaign.provider_status = "PAUSED"
        campaign.status = "paused"
        confirm_action(action, provider=result.provider, external_id=campaign.external_campaign_id)
        return f"Campaign paused on {result.provider}."
    fail_action(action, failure_class=result.failure_class or "TRANSIENT", error=result.reason, retryable=True)
    return result.reason or "Pause failed."


def sync_campaign(db: Session, *, tenant_id: UUID, actor_id: UUID | None, campaign: Campaign) -> Campaign:
    if not campaign.external_campaign_id:
        return campaign
    provider = get_ads_provider(campaign.channel, db, tenant_id)
    metrics = provider.get_metrics(external_id=campaign.external_campaign_id)
    if metrics.provider_status:
        campaign.provider_status = metrics.provider_status
    if metrics.spend is not None:
        campaign.spent = metrics.spend
    if metrics.impressions is not None:
        campaign.impressions = metrics.impressions
    if metrics.clicks is not None:
        campaign.clicks = metrics.clicks
    if metrics.conversions is not None:
        campaign.conversions = metrics.conversions
    derived = derived_metrics(metrics)
    campaign.ctr = derived["ctr"]
    campaign.cpc = derived["cpc"]
    campaign.cpl = derived["cpl"]
    today = datetime.now(UTC).date()
    daily = db.scalar(
        select(CampaignMetricDaily).where(
            CampaignMetricDaily.tenant_id == tenant_id,
            CampaignMetricDaily.campaign_id == campaign.id,
            CampaignMetricDaily.metric_date == today,
            CampaignMetricDaily.deleted_at.is_(None),
        )
    )
    if daily is None:
        daily = CampaignMetricDaily(tenant_id=tenant_id, created_by=actor_id, campaign_id=campaign.id, metric_date=today)
        db.add(daily)
    daily.spend = metrics.spend
    daily.impressions = metrics.impressions
    daily.clicks = metrics.clicks
    daily.conversions = metrics.conversions
    daily.ctr = derived["ctr"]
    daily.cpc = derived["cpc"]
    daily.cpl = derived["cpl"]
    daily.currency = metrics.currency
    campaign.last_synced_at = datetime.now(UTC)
    record_provider_result(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        provider=metrics.provider,
        action="ads.sync",
        ok=not metrics.reason.startswith("LinkedIn network") and not metrics.reason.startswith("Meta network"),
        error=metrics.reason,
    )
    return campaign


def sync_tenant_campaigns(db: Session, *, tenant_id: UUID, actor_id: UUID | None) -> int:
    rows = db.scalars(
        select(Campaign).where(
            Campaign.tenant_id == tenant_id,
            Campaign.deleted_at.is_(None),
            Campaign.external_campaign_id != "",
        )
    ).all()
    for campaign in rows:
        sync_campaign(db, tenant_id=tenant_id, actor_id=actor_id, campaign=campaign)
    return len(rows)


def queue_campaign_pause(db: Session, *, tenant_id: UUID, actor_id: UUID, campaign: Campaign) -> AIApproval:
    if not campaign.external_campaign_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campaign has no provider id to pause.")
    key = f"ads.pause:{campaign.id}"
    existing = db.scalar(select(AIApproval).where(AIApproval.tenant_id == tenant_id, AIApproval.idempotency_key == key, AIApproval.deleted_at.is_(None)))
    if existing:
        return existing
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="ads.pause",
        title=f"Pause {campaign.name}",
        payload_json=json.dumps({"campaign_id": str(campaign.id)}),
        status="pending",
        entity_type="campaign",
        entity_id=str(campaign.id),
        idempotency_key=key,
    )
    db.add(approval)
    db.flush()
    return approval


def queue_creative_draft(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    campaign: Campaign,
    headline: str,
    body: str,
    name: str = "",
) -> AIApproval:
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="ads.creative",
        title=f"Review ad creative for {campaign.name}",
        payload_json=json.dumps(
            {
                "campaign_id": str(campaign.id),
                "name": name or f"{campaign.name} creative",
                "headline": headline,
                "body": body,
            }
        ),
        status="pending",
        entity_type="campaign",
        entity_id=str(campaign.id),
    )
    db.add(approval)
    db.flush()
    return approval


def execute_ads_creative(db: Session, *, tenant_id: UUID, actor_id: UUID, approval: AIApproval) -> str:
    payload = json.loads(approval.payload_json or "{}")
    campaign = get_owned(db, Campaign, tenant_id, UUID(str(payload.get("campaign_id"))))
    row = AdCreative(
        tenant_id=tenant_id,
        created_by=actor_id,
        campaign_id=campaign.id,
        name=str(payload.get("name") or campaign.name),
        headline=str(payload.get("headline") or ""),
        body=str(payload.get("body") or ""),
        status="approved",
        provider=campaign.provider or campaign.channel,
        approval_id=approval.id,
    )
    db.add(row)
    if campaign.external_campaign_id:
        provider = get_ads_provider(campaign.channel, db, tenant_id)
        created = provider.create_creative(name=row.name, headline=row.headline, body=row.body)
        if created.ok:
            row.external_id = created.external_id
            row.status = "published"
            return f"Creative stored and sent to {created.provider}."
        row.last_error = created.reason
        return f"Creative stored locally. Provider did not publish: {created.reason}"
    return "Creative stored. It was not published because the campaign has no provider id."


def sync_consented_audience(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    campaign: Campaign,
    lookalike: bool = False,
) -> AdAudience:
    leads = db.scalars(select(Lead).where(Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None), Lead.consent_email.is_(True), Lead.opt_out.is_(False))).all()
    emails: list[str] = []
    for lead in leads:
        if email_block_reason(lead):
            continue
        if lead.email:
            emails.append(lead.email.strip().lower())
    contacts = db.scalars(select(Contact).where(Contact.tenant_id == tenant_id, Contact.deleted_at.is_(None), Contact.consent_email.is_(True), Contact.opt_out.is_(False))).all()
    for contact in contacts:
        if contact.email:
            emails.append(contact.email.strip().lower())
    identifiers = sorted(set(emails))
    audience = AdAudience(
        tenant_id=tenant_id,
        created_by=actor_id,
        campaign_id=campaign.id,
        name=f"{campaign.name} consented",
        provider=campaign.channel,
        member_count=len(identifiers),
        lookalike=lookalike,
        status="blocked" if not identifiers else "pending",
    )
    db.add(audience)
    if not identifiers:
        audience.last_error = "No consented identifiers. Nothing left the system."
        return audience
    provider = get_ads_provider(campaign.channel, db, tenant_id)
    result = provider.sync_audience(name=audience.name, identifiers=identifiers, lookalike=lookalike)
    audience.external_id = result.external_id
    audience.status = "synced" if result.ok else "failed"
    audience.last_error = result.reason
    return audience
