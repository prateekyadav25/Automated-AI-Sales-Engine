"""The Social Growth Command Center overview.

Every figure here is a stored count or a stored provider reading. Absent
evidence is reported as unavailable with its reason. Fixture evidence is
reported separately from live evidence.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.growth import (
    BrandFact,
    BrandProfile,
    GrowthCalendarItem,
    GrowthCreative,
    GrowthPublication,
)
from app.services.demo_guard import scope_for_execution
from app.services.growth.accounts import account_out, list_accounts
from app.services.growth.attribution import attribution_report
from app.services.growth.automation import automation_runs
from app.services.growth.common import growth_enabled, insights_mode, iso, now, operating_mode, publish_mode
from app.services.growth.governance import grants
from app.services.growth.recommendations import open_recommendations
from app.services.growth.render import RenderUnavailable, resolve_fonts
from app.services.growth.strategy import active_strategy, latest_strategy, strategy_out
from app.services.growth.video import VideoUnavailable, tools


def _capabilities() -> dict:
    try:
        resolve_fonts()
        fonts = {"ready": True, "detail": "TrueType fonts found."}
    except RenderUnavailable as exc:
        fonts = {"ready": False, "detail": str(exc)}
    try:
        tools()
        video = {"ready": True, "detail": "FFmpeg and ffprobe found."}
    except VideoUnavailable as exc:
        video = {"ready": False, "detail": str(exc)}
    settings = get_settings()
    return {
        "image_rendering": fonts,
        "video_rendering": video,
        "model_imagery": {"ready": bool(settings.gemini_image_model), "detail": "GEMINI_IMAGE_MODEL is set." if settings.gemini_image_model else "Off. Cards use brand templates without model imagery."},
        "graph_api_version": settings.meta_graph_api_version,
        "publish_mode": publish_mode(),
        "insights_mode": insights_mode(),
        "ga4_mode": (settings.ga4_mode or "disabled").strip().lower(),
        "brand_fetch_mode": (settings.social_growth_brand_fetch_mode or "live").strip().lower(),
        "public_media_base": settings.public_api_base_url,
        "public_media_ready": settings.public_api_base_url.startswith("https://") and "localhost" not in settings.public_api_base_url,
    }


def overview(db: Session, tenant_id: UUID) -> dict:
    moment = now()
    profile = db.scalar(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id, BrandProfile.deleted_at.is_(None)))
    fact_counts = {
        state: int(count)
        for state, count in db.execute(
            select(BrandFact.state, func.count()).where(BrandFact.tenant_id == tenant_id, BrandFact.deleted_at.is_(None)).group_by(BrandFact.state)
        ).all()
    }
    claims_waiting = int(
        db.scalar(select(func.count()).select_from(BrandFact).where(BrandFact.tenant_id == tenant_id, BrandFact.deleted_at.is_(None), BrandFact.category == "claim", BrandFact.state == "needs_review"))
        or 0
    )
    accounts = list_accounts(db, tenant_id)
    week = moment + timedelta(days=7)
    calendar = {
        status: int(count)
        for status, count in db.execute(
            select(GrowthCalendarItem.status, func.count())
            .where(GrowthCalendarItem.tenant_id == tenant_id, GrowthCalendarItem.deleted_at.is_(None), GrowthCalendarItem.planned_for >= moment, GrowthCalendarItem.planned_for < moment + timedelta(days=30))
            .group_by(GrowthCalendarItem.status)
        ).all()
    }
    next_week = int(
        db.scalar(
            select(func.count()).select_from(GrowthCalendarItem).where(
                GrowthCalendarItem.tenant_id == tenant_id,
                GrowthCalendarItem.deleted_at.is_(None),
                GrowthCalendarItem.planned_for >= moment,
                GrowthCalendarItem.planned_for < week,
                GrowthCalendarItem.status != "skipped",
            )
        )
        or 0
    )
    review = int(db.scalar(select(func.count()).select_from(GrowthCreative).where(GrowthCreative.tenant_id == tenant_id, GrowthCreative.deleted_at.is_(None), GrowthCreative.status.in_(["needs_review", "draft"]))) or 0)
    publications = {
        f"{provenance}:{status}": int(count)
        for provenance, status, count in db.execute(
            select(GrowthPublication.provenance, GrowthPublication.status, func.count())
            .where(GrowthPublication.tenant_id == tenant_id, GrowthPublication.deleted_at.is_(None))
            .group_by(GrowthPublication.provenance, GrowthPublication.status)
        ).all()
    }
    blocked = db.scalars(
        select(GrowthCalendarItem)
        .where(GrowthCalendarItem.tenant_id == tenant_id, GrowthCalendarItem.deleted_at.is_(None), GrowthCalendarItem.blocker != "", GrowthCalendarItem.status.in_(["blocked", "scheduled", "publishing", "needs_review"]))
        .order_by(GrowthCalendarItem.planned_for.asc())
        .limit(8)
    ).all()
    scope = scope_for_execution(db, tenant_id)
    strategy = active_strategy(db, tenant_id)
    draft = latest_strategy(db, tenant_id)
    attribution = attribution_report(db, tenant_id, start=moment - timedelta(days=30), end=moment + timedelta(minutes=1))
    return {
        "generated_at": iso(moment),
        "flag_enabled": growth_enabled(db, tenant_id),
        "operating_mode": operating_mode(db, tenant_id),
        "demo_scope": {"status": scope.status, "expires_at": iso(scope.expires_at)} if scope is not None else None,
        "brand": {
            "status": profile.status if profile is not None else "not_started",
            "website_url": profile.website_url if profile is not None else "",
            "company_name": profile.company_name if profile is not None else "",
            "last_analysis_at": iso(profile.last_analysis_at) if profile is not None else "",
            "facts": fact_counts,
            "claims_waiting": claims_waiting,
        },
        "accounts": [account_out(row) for row in accounts],
        "strategy": strategy_out(strategy),
        "draft_strategy": strategy_out(draft) if draft is not None and (strategy is None or draft.id != strategy.id) else None,
        "calendar": {"next_7_days": next_week, "next_30_days_by_status": calendar},
        "review_queue": review,
        "publications": publications,
        "attribution_30d": {
            "first_party_clicks": attribution["traffic"]["first_party_clicks"],
            "enquiries": attribution["enquiries"]["count"],
            "qualified_leads": attribution["qualified_leads"]["count"],
            "won_purchases": attribution["sales"]["won_purchases"],
            "ga4_status": attribution["traffic"]["ga4"]["status"],
        },
        "automation": {
            "capabilities": _capabilities(),
            "grants": grants(db, tenant_id),
            "runs": automation_runs(db, tenant_id),
            "blocked": [{"id": str(row.id), "status": row.status, "planned_for": iso(row.planned_for), "blocker": row.blocker} for row in blocked],
        },
        "recommendations": open_recommendations(db, tenant_id)[:6],
        "accounts_needing_attention": [account_out(row) for row in accounts if row.status in {"needs_reconnect", "expired", "missing_permissions", "unverified"}],
        "live_publication_count": sum(count for key, count in publications.items() if key == "live:published"),
        "account_count": len([row for row in accounts if row.status not in {"disconnected", "revoked"}]),
    }
