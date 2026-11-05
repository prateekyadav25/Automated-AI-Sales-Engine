"""Canonical tracking links, first-party clicks, enquiry attribution, and GA4 traffic.

Traffic, enquiries, qualified leads, and sales stay separate measurements.
A click is not a lead. A browser cannot choose the link: the server resolves
the token for one tenant. GA4 figures are stored only as GA4 returned them.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.tenant_context import set_form_token_hash, set_tenant_context
from app.models.acquisition import InboundCapture
from app.models.assessment import AssessmentDecision
from app.models.crm import Lead
from app.models.funnel import PublicFormKey
from app.models.growth import (
    BrandProfile,
    GrowthAccount,
    GrowthCalendarItem,
    GrowthLinkClick,
    GrowthStrategy,
    GrowthTrackingLink,
    GrowthTrafficObservation,
)
from app.models.lifecycle import DealPurchase
from app.providers.ga4 import SCOPE, run_traffic_report
from app.services.audit import write_audit
from app.services.growth.common import iso, now, operating_mode
from app.services.provider_accounts import connected_google_account, ensure_fresh_token, parse_scopes
from app.services.public_forms import form_key_url, hash_form_token

BOT_MARKERS = (
    "bot", "crawler", "spider", "facebookexternalhit", "meta-externalagent", "facebookcatalog", "slurp",
    "preview", "headless", "curl", "python-httpx", "python-requests", "wget", "monitor",
)
SOCIAL_SOURCES = {"facebook", "instagram", "fb", "ig", "m.facebook.com", "l.facebook.com", "lm.facebook.com", "facebook.com", "instagram.com", "l.instagram.com"}
UTM_MEDIUM = "social_organic"


def is_bot(user_agent: str) -> bool:
    folded = (user_agent or "").casefold()
    return not folded or any(marker in folded for marker in BOT_MARKERS)


def short_link(token: str) -> str:
    base = get_settings().public_api_base_url.rstrip("/") or "http://localhost:8000"
    return f"{base}/api/v1/public/r/{token}"


def _destination(db: Session, strategy: GrowthStrategy, account: GrowthAccount, item: GrowthCalendarItem, token: str) -> tuple[str, UUID | None]:
    params = {
        "utm_source": account.platform,
        "utm_medium": UTM_MEDIUM,
        "utm_campaign": f"social-growth-v{strategy.version}",
        "utm_content": item.slot_key.replace("#", "-")[:60],
    }
    if strategy.destination_kind == "form" and strategy.destination_form_key_id is not None:
        form = db.get(PublicFormKey, strategy.destination_form_key_id)
        base = form_key_url(form) if form is not None and form.tenant_id == item.tenant_id else ""
        if base:
            query = urlencode({"source": "social_post", "channel": account.platform, **params, "growth": token})
            return f"{base}?{query}", form.id
    base = strategy.destination_url
    if not base:
        return "", None
    join = "&" if "?" in base else "?"
    return f"{base}{join}{urlencode(params)}", None


def ensure_tracking_link(db: Session, *, tenant_id: UUID, actor_id: UUID | None, item: GrowthCalendarItem, strategy: GrowthStrategy, account: GrowthAccount) -> GrowthTrackingLink | None:
    if item.tracking_link_id is not None:
        existing = db.get(GrowthTrackingLink, item.tracking_link_id)
        if existing is not None and existing.tenant_id == tenant_id:
            return existing
    token = secrets.token_urlsafe(12)
    destination, form_id = _destination(db, strategy, account, item, token)
    if not destination:
        return None
    row = GrowthTrackingLink(
        tenant_id=tenant_id,
        created_by=actor_id,
        token=token,
        token_hash=hash_form_token(token),
        calendar_item_id=item.id,
        account_id=account.id,
        destination_url=destination[:1000],
        form_key_id=form_id,
        utm_source=account.platform,
        utm_medium=UTM_MEDIUM,
        utm_campaign=f"social-growth-v{strategy.version}",
        utm_content=item.slot_key.replace("#", "-")[:60],
    )
    db.add(row)
    db.flush()
    item.tracking_link_id = row.id
    return row


def resolve_redirect(db: Session, token: str, *, referer: str, user_agent: str) -> str | None:
    """Public redirect. The token hash is the only lookup key; the click is stored under that link's tenant."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token or ""):
        return None
    hashed = hash_form_token(token)
    set_form_token_hash(db, hashed)
    link = db.scalar(select(GrowthTrackingLink).where(GrowthTrackingLink.token_hash == hashed, GrowthTrackingLink.status == "active", GrowthTrackingLink.deleted_at.is_(None)))
    if link is None:
        return None
    set_tenant_context(db, link.tenant_id)
    db.add(
        GrowthLinkClick(
            tenant_id=link.tenant_id,
            link_id=link.id,
            clicked_at=now(),
            is_bot=is_bot(user_agent),
            referrer_host=(urlsplit(referer or "").hostname or "")[:200],
        )
    )
    db.flush()
    return link.destination_url


def link_for_capture(db: Session, tenant_id: UUID, token: str) -> GrowthTrackingLink | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token or ""):
        return None
    return db.scalar(
        select(GrowthTrackingLink).where(
            GrowthTrackingLink.tenant_id == tenant_id,
            GrowthTrackingLink.token_hash == hash_form_token(token),
            GrowthTrackingLink.deleted_at.is_(None),
        )
    )


def strategy_plan_for_link(db: Session, link: GrowthTrackingLink) -> UUID | None:
    if link.calendar_item_id is None:
        return None
    item = db.get(GrowthCalendarItem, link.calendar_item_id)
    strategy = db.get(GrowthStrategy, item.strategy_id) if item is not None else None
    if strategy is None or strategy.tenant_id != link.tenant_id:
        return None
    return strategy.operating_plan_id


def _range_filter(column, start: datetime, end: datetime):
    return (column >= start, column < end)


def attribution_report(db: Session, tenant_id: UUID, *, start: datetime, end: datetime, account_id: UUID | None = None) -> dict:
    link_stmt = select(GrowthTrackingLink).where(GrowthTrackingLink.tenant_id == tenant_id, GrowthTrackingLink.deleted_at.is_(None))
    if account_id is not None:
        link_stmt = link_stmt.where(GrowthTrackingLink.account_id == account_id)
    links = list(db.scalars(link_stmt).all())
    link_ids = [row.id for row in links]
    clicks_human = clicks_bot = 0
    if link_ids:
        for is_bot_click, count in db.execute(
            select(GrowthLinkClick.is_bot, func.count())
            .where(GrowthLinkClick.tenant_id == tenant_id, GrowthLinkClick.link_id.in_(link_ids), *_range_filter(GrowthLinkClick.clicked_at, start, end))
            .group_by(GrowthLinkClick.is_bot)
        ).all():
            if is_bot_click:
                clicks_bot = int(count)
            else:
                clicks_human = int(count)
    captures = list(
        db.scalars(
            select(InboundCapture).where(
                InboundCapture.tenant_id == tenant_id,
                InboundCapture.deleted_at.is_(None),
                InboundCapture.growth_link_id.in_(link_ids),
                *_range_filter(InboundCapture.created_at, start, end),
            )
        ).all()
    ) if link_ids else []
    lead_ids = list({row.lead_id for row in captures if row.lead_id is not None})
    leads = list(db.scalars(select(Lead).where(Lead.tenant_id == tenant_id, Lead.id.in_(lead_ids))).all()) if lead_ids else []
    qualified = 0
    if lead_ids:
        qualified = len(
            {
                row.lead_id
                for row in db.scalars(
                    select(AssessmentDecision).where(
                        AssessmentDecision.tenant_id == tenant_id,
                        AssessmentDecision.lead_id.in_(lead_ids),
                        AssessmentDecision.deleted_at.is_(None),
                        AssessmentDecision.sales_qualified.is_(True),
                    )
                ).all()
            }
        )
    account_ids = list({lead.account_id for lead in leads if lead.account_id is not None})
    real: dict[str, Decimal] = {}
    fixture: dict[str, Decimal] = {}
    won = 0
    if account_ids:
        for purchase in db.scalars(
            select(DealPurchase).where(
                DealPurchase.tenant_id == tenant_id,
                DealPurchase.account_id.in_(account_ids),
                DealPurchase.deleted_at.is_(None),
                DealPurchase.status == "won",
            )
        ).all():
            won += 1
            bucket = fixture if purchase.fixture else real
            key = purchase.currency or "unknown"
            bucket[key] = bucket.get(key, Decimal("0")) + (purchase.amount or Decimal("0"))
    traffic = traffic_summary(db, tenant_id, start=start, end=end)
    per_account: dict[str, dict] = {}
    for link in links:
        key = str(link.account_id or "")
        per_account.setdefault(key, {"links": 0, "enquiries": 0})
        per_account[key]["links"] += 1
    for capture in captures:
        link = next((row for row in links if row.id == capture.growth_link_id), None)
        if link is not None:
            per_account.setdefault(str(link.account_id or ""), {"links": 0, "enquiries": 0})["enquiries"] += 1
    return {
        "range": {"start": iso(start), "end": iso(end)},
        "traffic": {
            "first_party_clicks": clicks_human,
            "bot_clicks_excluded": clicks_bot,
            "definition": "Redirects through this engine's tracking links. Automated agents are counted separately and excluded.",
            "ga4": traffic,
        },
        "enquiries": {"count": len(captures), "leads": len(lead_ids), "definition": "Form submissions that carried a growth tracking token for this workspace."},
        "qualified_leads": {"count": qualified, "definition": "Attributed leads with a stored sales-qualified assessment."},
        "sales": {
            "won_purchases": won,
            "amounts": {currency: str(amount) for currency, amount in real.items()},
            "fixture_amounts": {currency: str(amount) for currency, amount in fixture.items()},
            "definition": "Evidence-backed close-won purchases on the accounts of attributed leads. Currencies are not combined. Fixture amounts are separate.",
        },
        "per_account": per_account,
    }


def traffic_summary(db: Session, tenant_id: UUID, *, start: datetime, end: datetime) -> dict:
    profile = db.scalar(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id, BrandProfile.deleted_at.is_(None)))
    property_id = profile.ga4_property_id if profile is not None else ""
    if not property_id:
        return {"status": "not_configured", "detail": "No GA4 property is saved. Website sessions are unavailable, not zero.", "rows": []}
    first, last = start.date().isoformat(), (end - timedelta(seconds=1)).date().isoformat()
    rows = db.scalars(
        select(GrowthTrafficObservation).where(
            GrowthTrafficObservation.tenant_id == tenant_id,
            GrowthTrafficObservation.property_id == property_id,
            GrowthTrafficObservation.day >= first,
            GrowthTrafficObservation.day <= last,
            GrowthTrafficObservation.deleted_at.is_(None),
        )
    ).all()
    if not rows:
        return {"status": "unavailable", "detail": "No GA4 rows are stored for this range.", "rows": [], "property_id": property_id}
    social = [row for row in rows if row.source.casefold() in SOCIAL_SOURCES or row.medium.casefold() == UTM_MEDIUM]
    days = {row.day for row in rows}
    span = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in social:
        key = (row.source, row.medium, row.campaign)
        entry = grouped.setdefault(key, {"source": row.source, "medium": row.medium, "campaign": row.campaign, "sessions": None, "total_users_daily_sum": None, "key_events": None})
        for field, value in (("sessions", row.sessions), ("total_users_daily_sum", row.total_users), ("key_events", row.key_events)):
            if value is not None:
                entry[field] = (entry[field] or 0) + value
    latest = max(row.retrieved_at for row in rows)
    return {
        "status": "recorded",
        "property_id": property_id,
        "coverage_days": len(days),
        "range_days": span,
        "retrieved_at": iso(latest),
        "rows": sorted(grouped.values(), key=lambda item: -(item["sessions"] or 0)),
        "note": "Users are summed across days and are not de-duplicated. Missing days stay missing.",
    }


def collect_ga4(db: Session, *, tenant_id: UUID, actor_id: UUID | None, client=None, token: str = "", provenance: str = "live", days: int = 30) -> dict:
    profile = db.scalar(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id, BrandProfile.deleted_at.is_(None)))
    property_id = profile.ga4_property_id if profile is not None else ""
    if not property_id:
        return {"status": "blocked", "stored": 0, "detail": "Save the GA4 property id first."}
    owned = False
    if client is None:
        if (get_settings().ga4_mode or "disabled").strip().lower() != "live":
            return {"status": "blocked", "stored": 0, "detail": "GA4 reads are disabled in this deployment (GA4_MODE). Nothing was requested."}
        if operating_mode(db, tenant_id) == "DEMO":
            return {"status": "blocked", "stored": 0, "detail": "A DEMO workspace does not read GA4. Nothing was requested."}
        account = connected_google_account(db, tenant_id)
        if account is None or SCOPE not in parse_scopes(account.scopes):
            return {"status": "blocked", "stored": 0, "detail": "The Google connection lacks analytics.readonly. Reconnect Google with that scope."}
        settings = get_settings()
        token = ensure_fresh_token(db, account, client_id=settings.google_client_id, client_secret=settings.google_client_secret)
        client = httpx.Client(timeout=30.0)
        owned = True
    end_day = datetime.now(UTC).date() - timedelta(days=1)
    start_day = end_day - timedelta(days=max(1, days) - 1)
    try:
        result = run_traffic_report(client, token=token, property_id=property_id, start_date=start_day.isoformat(), end_date=end_day.isoformat())
    finally:
        if owned:
            client.close()
    if not result["ok"]:
        return {"status": "failed", "stored": 0, "detail": result["error"]}
    stored = 0
    for row in result["rows"]:
        existing = db.scalar(
            select(GrowthTrafficObservation).where(
                GrowthTrafficObservation.tenant_id == tenant_id,
                GrowthTrafficObservation.property_id == property_id,
                GrowthTrafficObservation.day == row["day"],
                GrowthTrafficObservation.source == row["source"][:200],
                GrowthTrafficObservation.medium == row["medium"][:200],
                GrowthTrafficObservation.campaign == row["campaign"][:200],
            )
        )
        if existing is None:
            existing = GrowthTrafficObservation(
                tenant_id=tenant_id,
                created_by=actor_id,
                property_id=property_id,
                day=row["day"],
                source=row["source"][:200],
                medium=row["medium"][:200],
                campaign=row["campaign"][:200],
                retrieved_at=now(),
            )
            db.add(existing)
        existing.sessions = row["sessions"]
        existing.total_users = row["total_users"]
        existing.key_events = row["key_events"]
        existing.status = "recorded"
        existing.retrieved_at = now()
        existing.provenance = provenance
        stored += 1
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.ga4_collect", entity_type="brand_profile", entity_id=str(profile.id), after={"stored": stored, "provenance": provenance}, actor_type="human" if actor_id else "ai")
    return {"status": result["status"], "stored": stored, "detail": result["error"] or f"Stored {stored} GA4 row(s)."}
