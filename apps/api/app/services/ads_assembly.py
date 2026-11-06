"""Paused Meta campaign, ad set, creative, and ad for one website capture form.

A saved proposal and a positive budget do not activate delivery. This module
does not call activate_campaign or execute_ads_spend. LinkedIn is not mapped
onto Meta's object tree. A provider client is used only when the caller
supplies one; this milestone does not open a live Meta connection.
"""

from __future__ import annotations

import json
import secrets
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.acquisition import InboundCapture
from app.models.funnel import AdCreative, AdSet, PaidAd, PublicFormKey
from app.models.integrations import ProviderAction
from app.models.lifecycle import Campaign
from app.models.operating_plan import CreativeVersion, OperatingPlan
from app.providers.ads import MetaAdsProvider, PreparedAdsProvider
from app.providers.meta_growth import graph_base
from app.services.demo_guard import ads_assembly_block
from app.services.product_context import build_product_context
from app.services.provider_ops import begin_action, confirm_action
from app.services.public_forms import form_key_url
from app.services.query import get_owned

WEBSITE_DESTINATION = "website_form"
SUPPORTED_OBJECTIVE = "traffic"
SUPPORTED_PLACEMENT = "facebook_feed"
SUPPORTED_CALLS = {"LEARN_MORE", "SIGN_UP", "CONTACT_US"}
ASSEMBLY_VERSION = "meta-paused-website-v21.0"
UNSUPPORTED_LINKEDIN = (
    "LinkedIn campaign assembly is not implemented. Meta's campaign, ad set, creative, and ad structure was not applied."
)
UNSUPPORTED_DESTINATION = (
    "Only a paused website-traffic campaign to the existing capture form is supported. "
    "A native lead form is not created or launched here."
)
ADAPTER_INCOMPLETE = "This adapter cannot report a completed live-capable campaign."
NO_LIVE_CLIENT = "This assembly does not open a live Meta client. Nothing was created."


def _placements(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(loaded, list):
            return [str(item).strip() for item in loaded if str(item).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def proposal_errors(db: Session, *, tenant_id: UUID, campaign: Campaign) -> list[str]:
    errors: list[str] = []
    if not (campaign.name or "").strip():
        errors.append("A campaign name is required.")
    if (campaign.channel or "").strip().lower() != "meta":
        return errors
    if (campaign.objective or "").strip().lower() != SUPPORTED_OBJECTIVE:
        errors.append(UNSUPPORTED_DESTINATION)
    if (campaign.destination or "").strip().lower() != WEBSITE_DESTINATION:
        errors.append(UNSUPPORTED_DESTINATION)
    if not (campaign.audience or "").strip():
        errors.append("An intended audience is required.")
    geography = (campaign.geography or "").strip().upper()
    if len(geography) != 2 or not geography.isalpha():
        errors.append("Geography must be a two-letter country code.")
    if _placements(campaign.placements) != [SUPPORTED_PLACEMENT]:
        errors.append("The only supported placement is facebook_feed.")
    if campaign.start_date is None or campaign.end_date is None or campaign.end_date <= campaign.start_date:
        errors.append("A start date and a later end date are required.")
    timezone = (campaign.timezone or "").strip()
    if timezone != "UTC" and "/" not in timezone:
        errors.append("A time zone is required.")
    budget = Decimal(str(campaign.budget or 0))
    if budget <= 0:
        errors.append("A proposed budget greater than zero is required. It does not authorize spend.")
    currency = (campaign.currency or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        errors.append("A three-letter currency is required.")
    if not (campaign.headline or "").strip() or not (campaign.body or "").strip():
        errors.append("Copy and a headline are required.")
    if (campaign.call_to_action or "").strip().upper() not in SUPPORTED_CALLS:
        errors.append("The call to action must be LEARN_MORE, SIGN_UP, or CONTACT_US.")
    if not (campaign.asset_ref or "").strip():
        errors.append("A creative asset is required.")
    if campaign.operating_plan_id is None:
        errors.append("An operating plan is required.")
    else:
        plan = db.get(OperatingPlan, campaign.operating_plan_id)
        if plan is None or plan.tenant_id != tenant_id or plan.deleted_at is not None:
            errors.append("The operating plan is not in this workspace.")
        elif plan.product_id is None:
            errors.append("The operating plan has no product.")
        elif plan.form_key_id is None:
            errors.append("The operating plan has no capture form.")
    if campaign.creative_version_id is None:
        errors.append("A creative version is required.")
    else:
        version = db.get(CreativeVersion, campaign.creative_version_id)
        if version is None or version.tenant_id != tenant_id or version.deleted_at is not None:
            errors.append("The creative version is not in this workspace.")
        elif campaign.operating_plan_id is not None and version.plan_id != campaign.operating_plan_id:
            errors.append("The creative version belongs to a different operating plan.")
    return errors


def _save(campaign: Campaign, *, assembly_status: str, blocker: str) -> dict:
    campaign.assembly_status = assembly_status
    campaign.assembly_blocker = blocker
    if campaign.status == "launched":
        campaign.status = "paused" if assembly_status == "paused" else campaign.status
    return _result(campaign)


def _result(campaign: Campaign) -> dict:
    return {
        "campaign_id": str(campaign.id),
        "assembly_status": campaign.assembly_status,
        "blocker": campaign.assembly_blocker,
        "activated": False,
        "external_campaign_id": campaign.external_campaign_id,
        "provider_status": campaign.provider_status,
        "graph": graph_base(),
        "contract": ASSEMBLY_VERSION,
    }


def _local_execution_note(url: str, asset: str, page_id: str) -> str:
    notes: list[str] = []
    host = (urlparse(url).hostname or "").lower()
    if not url or host in {"localhost", "127.0.0.1"} or host.endswith(".local"):
        notes.append("The capture destination is local. Live execution is not ready.")
    asset_host = (urlparse(asset).hostname or "").lower() if "://" in asset else ""
    if not asset.startswith("https://") or asset_host in {"localhost", "127.0.0.1"} or asset.startswith("/") or asset.startswith("file:"):
        notes.append("The creative asset is local. Live execution is not ready.")
    if not page_id.strip():
        notes.append("No Meta page id is configured for the creative. Live execution is not ready.")
    notes.append("Paid impressions, clicks, and spend have not been read back.")
    return " ".join(notes)


def _explicit_meta(provider: object) -> MetaAdsProvider | None:
    if isinstance(provider, MetaAdsProvider) and provider._client is not None:
        return provider
    return None


def _step_action(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    campaign_id: UUID,
    step: str,
) -> ProviderAction:
    return begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="ads.assemble",
        idempotency_key=f"ads.assemble:{campaign_id}:{step}",
        provider="meta-ads",
        entity_type="campaign",
        entity_id=str(campaign_id),
        request_summary=f"paused website {step}",
    )


def _unresolved(action: ProviderAction) -> bool:
    if action.status == "UNRESOLVED":
        return True
    return action.status == "REQUESTED" and action.attempts >= 1 and not action.external_id


def _mark_attempt(action: ProviderAction) -> None:
    action.status = "REQUESTED"
    action.attempts = int(action.attempts or 0) + 1


def assemble_paused_meta(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    campaign: Campaign,
    provider: object | None = None,
) -> dict:
    channel = (campaign.channel or "").strip().lower()
    if channel == "linkedin":
        return _save(campaign, assembly_status="unsupported", blocker=UNSUPPORTED_LINKEDIN)
    if channel != "meta":
        return _save(
            campaign,
            assembly_status="unsupported",
            blocker="Only a Meta campaign can use this paused assembly.",
        )
    objective = (campaign.objective or "").strip().lower()
    destination = (campaign.destination or "").strip().lower()
    if objective != SUPPORTED_OBJECTIVE or destination != WEBSITE_DESTINATION:
        return _save(campaign, assembly_status="unsupported", blocker=UNSUPPORTED_DESTINATION)
    errors = proposal_errors(db, tenant_id=tenant_id, campaign=campaign)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=" ".join(errors))

    meta = _explicit_meta(provider)
    if meta is None:
        blocked = ads_assembly_block(db, tenant_id)
        if blocked:
            return _save(campaign, assembly_status="blocked", blocker=blocked)
        if provider is None or isinstance(provider, PreparedAdsProvider) or not isinstance(provider, MetaAdsProvider):
            return _save(campaign, assembly_status="unsupported", blocker=ADAPTER_INCOMPLETE)
        return _save(campaign, assembly_status="blocked", blocker=NO_LIVE_CLIENT)

    plan = get_owned(db, OperatingPlan, tenant_id, campaign.operating_plan_id)
    version = get_owned(db, CreativeVersion, tenant_id, campaign.creative_version_id)
    context = build_product_context(db, tenant_id, plan=plan)
    campaign.context_json = json.dumps(context.as_dict())
    if not (version.context_json or "").strip():
        version.context_json = campaign.context_json

    campaign_external = _campaign_object(db, tenant_id=tenant_id, actor_id=actor_id, campaign=campaign, provider=meta)
    if campaign_external is None:
        return _result(campaign)
    ad_set = _ad_set_object(db, tenant_id=tenant_id, actor_id=actor_id, campaign=campaign, provider=meta, parent_id=campaign_external)
    if ad_set is None:
        return _result(campaign)
    paid = _tracking_ad(db, tenant_id=tenant_id, actor_id=actor_id, campaign=campaign, ad_set=ad_set, version=version, plan=plan)
    creative = _creative_object(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        campaign=campaign,
        provider=meta,
        ad_set=ad_set,
        paid=paid,
    )
    if creative is None:
        return _result(campaign)
    ad_external = _ad_object(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        campaign=campaign,
        provider=meta,
        ad_set=ad_set,
        creative=creative,
        paid=paid,
    )
    if ad_external is None:
        return _result(campaign)
    campaign.status = "paused"
    campaign.provider = "meta-ads"
    campaign.provider_status = "PAUSED"
    campaign.assembly_status = "paused"
    campaign.assembly_blocker = ""
    db.flush()
    return _result(campaign)


def _fail(campaign: Campaign, action: ProviderAction, *, assembly_status: str, reason: str) -> None:
    action.failure_class = "UNKNOWN" if assembly_status == "unresolved" else action.failure_class or "PERMANENT"
    action.last_error = reason
    action.status = "UNRESOLVED" if assembly_status == "unresolved" else "FAILED"
    campaign.assembly_status = assembly_status
    campaign.assembly_blocker = reason
    campaign.status = "partial"
    db_flush = campaign
    _ = db_flush


def _campaign_object(db: Session, *, tenant_id: UUID, actor_id: UUID, campaign: Campaign, provider: MetaAdsProvider) -> str | None:
    if campaign.external_campaign_id:
        return campaign.external_campaign_id
    action = _step_action(db, tenant_id=tenant_id, actor_id=actor_id, campaign_id=campaign.id, step="campaign")
    if action.status == "CONFIRMED" and action.external_id:
        campaign.external_campaign_id = action.external_id
        campaign.provider = "meta-ads"
        campaign.provider_status = "PAUSED"
        db.flush()
        return action.external_id
    if _unresolved(action):
        _fail(campaign, action, assembly_status="unresolved", reason=action.last_error or "The campaign create is unresolved. It was not repeated.")
        db.flush()
        return None
    _mark_attempt(action)
    db.flush()
    result = provider.create_campaign(
        name=campaign.name,
        objective="website",
        budget=Decimal(str(campaign.budget)),
        include_budget=False,
    )
    if result.failure_class == "UNKNOWN" or result.provider_status == "unknown":
        _fail(campaign, action, assembly_status="unresolved", reason=result.reason)
        db.flush()
        return None
    if not result.ok or not result.external_id or result.provider_status != "PAUSED":
        action.failure_class = result.failure_class or "PERMANENT"
        _fail(campaign, action, assembly_status="partial", reason=result.reason or "Meta did not return a paused campaign id.")
        db.flush()
        return None
    confirm_action(action, provider=result.provider, external_id=result.external_id, response_summary="paused campaign")
    campaign.external_campaign_id = result.external_id
    campaign.provider = "meta-ads"
    campaign.provider_status = "PAUSED"
    campaign.status = "partial"
    campaign.assembly_status = "partial"
    campaign.assembly_blocker = "The campaign shell exists. The ad set, creative, and ad are not complete."
    db.flush()
    return result.external_id


def _ad_set_object(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    campaign: Campaign,
    provider: MetaAdsProvider,
    parent_id: str,
) -> AdSet | None:
    existing = db.scalar(
        select(AdSet).where(
            AdSet.tenant_id == tenant_id,
            AdSet.campaign_id == campaign.id,
            AdSet.deleted_at.is_(None),
            AdSet.external_id != "",
        )
    )
    if existing is not None:
        return existing
    action = _step_action(db, tenant_id=tenant_id, actor_id=actor_id, campaign_id=campaign.id, step="adset")
    if action.status == "CONFIRMED" and action.external_id:
        row = AdSet(
            tenant_id=tenant_id,
            created_by=actor_id,
            campaign_id=campaign.id,
            name=campaign.name,
            provider="meta-ads",
            external_id=action.external_id,
            status="paused",
            daily_budget=campaign.budget,
        )
        db.add(row)
        db.flush()
        return row
    if _unresolved(action):
        _fail(campaign, action, assembly_status="unresolved", reason=action.last_error or "The ad set create is unresolved. It was not repeated.")
        db.flush()
        return None
    _mark_attempt(action)
    db.flush()
    result = provider.create_ad_set(
        campaign_external_id=parent_id,
        name=campaign.name,
        budget=Decimal(str(campaign.budget)),
        countries=[campaign.geography.strip().upper()],
        optimization_goal="LINK_CLICKS",
        destination_type="WEBSITE",
        placements=[SUPPORTED_PLACEMENT],
        include_budget=True,
    )
    if result.failure_class == "UNKNOWN" or result.provider_status == "unknown":
        _fail(campaign, action, assembly_status="unresolved", reason=result.reason)
        db.flush()
        return None
    if not result.ok or not result.external_id or result.provider_status != "PAUSED":
        action.failure_class = result.failure_class or "PERMANENT"
        _fail(campaign, action, assembly_status="partial", reason=result.reason or "Meta did not return a paused ad set id.")
        db.flush()
        return None
    confirm_action(action, provider=result.provider, external_id=result.external_id, response_summary=f"parent={parent_id}")
    row = AdSet(
        tenant_id=tenant_id,
        created_by=actor_id,
        campaign_id=campaign.id,
        name=campaign.name,
        provider="meta-ads",
        external_id=result.external_id,
        status="paused",
        daily_budget=campaign.budget,
    )
    db.add(row)
    campaign.assembly_status = "partial"
    campaign.assembly_blocker = "The campaign and ad set exist. The creative and ad are not complete."
    db.flush()
    return row


def _tracking_ad(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    campaign: Campaign,
    ad_set: AdSet,
    version: CreativeVersion,
    plan: OperatingPlan,
) -> PaidAd:
    existing = db.scalar(
        select(PaidAd).where(PaidAd.tenant_id == tenant_id, PaidAd.campaign_id == campaign.id, PaidAd.deleted_at.is_(None))
    )
    if existing is not None:
        existing.ad_set_id = ad_set.id
        return existing
    form = db.get(PublicFormKey, plan.form_key_id) if plan.form_key_id else None
    base = form_key_url(form) if form is not None else ""
    token = secrets.token_hex(16)
    join = "&" if "?" in base else "?"
    url = f"{base}{join}ad={token}" if base else ""
    row = PaidAd(
        tenant_id=tenant_id,
        created_by=actor_id,
        campaign_id=campaign.id,
        ad_set_id=ad_set.id,
        creative_version_id=version.id,
        name=campaign.name,
        provider="meta-ads",
        external_id="",
        status="pending",
        tracking_token=token,
        destination_url=url,
    )
    db.add(row)
    db.flush()
    return row


def _creative_object(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    campaign: Campaign,
    provider: MetaAdsProvider,
    ad_set: AdSet,
    paid: PaidAd,
) -> AdCreative | None:
    existing = db.scalar(
        select(AdCreative).where(
            AdCreative.tenant_id == tenant_id,
            AdCreative.campaign_id == campaign.id,
            AdCreative.deleted_at.is_(None),
            AdCreative.external_id != "",
        )
    )
    if existing is not None:
        paid.ad_creative_id = existing.id
        return existing
    action = _step_action(db, tenant_id=tenant_id, actor_id=actor_id, campaign_id=campaign.id, step="creative")
    if _unresolved(action):
        _fail(campaign, action, assembly_status="unresolved", reason=action.last_error or "The creative create is unresolved. It was not repeated.")
        db.flush()
        return None
    if not (action.status == "CONFIRMED" and action.external_id):
        _mark_attempt(action)
        db.flush()
        result = provider.create_creative(
            name=campaign.name,
            headline=campaign.headline,
            body=campaign.body,
            link=paid.destination_url,
            call_to_action=campaign.call_to_action.strip().upper(),
            page_id=(get_settings().meta_page_id or "").strip(),
        )
        if result.failure_class == "UNKNOWN" or result.provider_status == "unknown":
            _fail(campaign, action, assembly_status="unresolved", reason=result.reason)
            db.flush()
            return None
        if not result.ok or not result.external_id:
            action.failure_class = result.failure_class or "PERMANENT"
            _fail(campaign, action, assembly_status="partial", reason=result.reason or "Meta did not return a creative id.")
            db.flush()
            return None
        confirm_action(action, provider=result.provider, external_id=result.external_id, response_summary="paused creative")
        external_id = result.external_id
    else:
        external_id = action.external_id
    row = AdCreative(
        tenant_id=tenant_id,
        created_by=actor_id,
        campaign_id=campaign.id,
        ad_set_id=ad_set.id,
        name=campaign.name,
        headline=campaign.headline,
        body=campaign.body,
        status="paused",
        provider="meta-ads",
        external_id=external_id,
    )
    db.add(row)
    db.flush()
    paid.ad_creative_id = row.id
    campaign.assembly_status = "partial"
    campaign.assembly_blocker = "The campaign, ad set, and creative exist. The ad is not complete."
    db.flush()
    return row


def _ad_object(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    campaign: Campaign,
    provider: MetaAdsProvider,
    ad_set: AdSet,
    creative: AdCreative,
    paid: PaidAd,
) -> str | None:
    if paid.external_id:
        paid.status = "paused"
        return paid.external_id
    action = _step_action(db, tenant_id=tenant_id, actor_id=actor_id, campaign_id=campaign.id, step="ad")
    if action.status == "CONFIRMED" and action.external_id:
        paid.external_id = action.external_id
        paid.status = "paused"
        paid.provider = "meta-ads"
        db.flush()
        return action.external_id
    if _unresolved(action):
        _fail(campaign, action, assembly_status="unresolved", reason=action.last_error or "The ad create is unresolved. It was not repeated.")
        db.flush()
        return None
    _mark_attempt(action)
    db.flush()
    result = provider.create_ad(ad_set_external_id=ad_set.external_id, creative_external_id=creative.external_id, name=campaign.name)
    if result.failure_class == "UNKNOWN" or result.provider_status == "unknown":
        _fail(campaign, action, assembly_status="unresolved", reason=result.reason)
        db.flush()
        return None
    if not result.ok or not result.external_id or result.provider_status != "PAUSED":
        action.failure_class = result.failure_class or "PERMANENT"
        _fail(campaign, action, assembly_status="partial", reason=result.reason or "Meta did not return a paused ad id.")
        db.flush()
        return None
    confirm_action(action, provider=result.provider, external_id=result.external_id, response_summary=f"adset={ad_set.external_id}")
    paid.external_id = result.external_id
    paid.status = "paused"
    paid.provider = "meta-ads"
    paid.last_error = ""
    db.flush()
    return result.external_id


def assembly_view(db: Session, campaign: Campaign, *, include_enquiries: bool) -> dict:
    ad_set = db.scalar(
        select(AdSet).where(AdSet.tenant_id == campaign.tenant_id, AdSet.campaign_id == campaign.id, AdSet.deleted_at.is_(None))
    )
    creative = db.scalar(
        select(AdCreative).where(
            AdCreative.tenant_id == campaign.tenant_id,
            AdCreative.campaign_id == campaign.id,
            AdCreative.deleted_at.is_(None),
        )
    )
    paid = db.scalar(
        select(PaidAd).where(PaidAd.tenant_id == campaign.tenant_id, PaidAd.campaign_id == campaign.id, PaidAd.deleted_at.is_(None))
    )
    offer = ""
    if (campaign.context_json or "").strip():
        try:
            loaded = json.loads(campaign.context_json)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            offer = str(loaded.get("customer_facing_name") or loaded.get("sku") or "")
    url = paid.destination_url if paid is not None else ""
    note = _local_execution_note(url, campaign.asset_ref or "", (get_settings().meta_page_id or "").strip())
    enquiries: list[dict] = []
    if include_enquiries:
        rows = db.scalars(
            select(InboundCapture)
            .where(
                InboundCapture.tenant_id == campaign.tenant_id,
                InboundCapture.campaign_id == campaign.id,
                InboundCapture.deleted_at.is_(None),
            )
            .order_by(InboundCapture.captured_at.asc())
        ).all()
        for index, row in enumerate(rows):
            enquiries.append(
                {
                    "capture_id": str(row.id),
                    "lead_id": str(row.lead_id) if row.lead_id else "",
                    "status": row.status,
                    "first_touch": index == 0,
                }
            )
    dates = ""
    if campaign.start_date or campaign.end_date:
        start = campaign.start_date.isoformat() if isinstance(campaign.start_date, date) else ""
        end = campaign.end_date.isoformat() if isinstance(campaign.end_date, date) else ""
        dates = f"{start} to {end} {campaign.timezone}".strip()
    return {
        "offer_label": offer,
        "live_execution_ready": False,
        "live_execution_note": note,
        "activated": False,
        "destination_url": url,
        "schedule_label": dates,
        "ad_set_external_id": ad_set.external_id if ad_set is not None else "",
        "creative_external_id": creative.external_id if creative is not None else "",
        "ad_external_id": paid.external_id if paid is not None else "",
        "ad_set_status": ad_set.status if ad_set is not None else "",
        "creative_status": creative.status if creative is not None else "",
        "ad_status": paid.status if paid is not None else "",
        "enquiries": enquiries,
    }


def paused_meta_summary(db: Session, tenant_id: UUID) -> dict:
    campaign = db.scalar(
        select(Campaign)
        .where(Campaign.tenant_id == tenant_id, Campaign.channel == "meta", Campaign.deleted_at.is_(None))
        .order_by(Campaign.created_at.desc())
    )
    if campaign is None:
        return {
            "present": False,
            "note": "No paused Meta campaign is stored. Native lead-form campaigns are not created here.",
        }
    view = assembly_view(db, campaign, include_enquiries=True)
    return {
        "present": True,
        "campaign_id": str(campaign.id),
        "name": campaign.name,
        "product": view["offer_label"],
        "objective": campaign.objective,
        "audience": campaign.audience,
        "geography": campaign.geography,
        "schedule": view["schedule_label"],
        "destination": campaign.destination,
        "destination_url": view["destination_url"],
        "proposed_budget": str(campaign.budget),
        "currency": campaign.currency,
        "headline": campaign.headline,
        "body": campaign.body,
        "call_to_action": campaign.call_to_action,
        "asset_ref": campaign.asset_ref,
        "assembly_status": campaign.assembly_status,
        "blocker": campaign.assembly_blocker,
        "activated": False,
        "live_execution_ready": False,
        "live_execution_note": view["live_execution_note"],
        "ad_set_status": view["ad_set_status"],
        "creative_status": view["creative_status"],
        "ad_status": view["ad_status"],
        "enquiries": view["enquiries"],
        "native_lead_form_campaigns": "Not created or launched by this website-destination assembly.",
    }
