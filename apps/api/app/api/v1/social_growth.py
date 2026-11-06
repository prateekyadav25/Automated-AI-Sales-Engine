"""Social Growth Autopilot routes. Services hold the rules; these routes check permissions and commit.

No route opens a live Meta or GA4 client. Live reads and publishing happen only
when the deployment modes are live and the workspace gates allow them.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.funnel import PublicFormKey
from app.models.growth import GrowthBusinessEvent, GrowthPublication
from app.schemas.common import Envelope
from app.schemas.growth import (
    AcceptanceIn,
    AccountUpdateIn,
    AnalyzeIn,
    BrandFactIn,
    BrandSettingsIn,
    CaptionIn,
    CompetitorsIn,
    DecideIn,
    EventIn,
    FactReviewIn,
    FixtureAccountIn,
    GrowthAccountIn,
    GrowthGrantIn,
    PauseIn,
    ResolveIn,
    ReviewIn,
    SkipIn,
    StrategyIn,
)
from app.services.audit import write_audit
from app.services.growth import acceptance as acceptance_service
from app.services.growth import accounts as account_service
from app.services.growth import brand as brand_service
from app.services.growth import creative as creative_service
from app.services.growth import governance, history, insights, planner, publisher, recommendations
from app.services.growth import strategy as strategy_service
from app.services.growth.attribution import attribution_report, collect_ga4
from app.services.growth.brand_extract import normalize_url
from app.services.growth.command_center import overview

router = APIRouter(prefix="/social-growth", tags=["social-growth"])
READ = "social_growth.read"
WRITE = "social_growth.write"
APPROVE = "social_growth.approve"
RANGES = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}


def period(range_: str, start: str, end: str) -> tuple[datetime, datetime]:
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if range_ != "custom":
        days = RANGES.get(range_)
        if days is None:
            raise HTTPException(status_code=422, detail="Range must be 1d, 7d, 30d, 90d, or custom.")
        return tomorrow - timedelta(days=days), tomorrow
    try:
        first = datetime.fromisoformat(start).replace(tzinfo=UTC, hour=0, minute=0, second=0, microsecond=0)
        last = datetime.fromisoformat(end).replace(tzinfo=UTC, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Custom ranges need start and end as YYYY-MM-DD.") from exc
    if last <= first or (last - first).days > 366:
        raise HTTPException(status_code=422, detail="A custom range must end after it starts and span at most 366 days.")
    return first, last


@router.get("/overview")
def get_overview(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))]) -> Envelope[dict]:
    return Envelope(data=overview(db, ctx.tenant_id))


@router.get("/brand")
def get_brand(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))]) -> Envelope[dict]:
    return Envelope(data=brand_service.brand_view(db, ctx.tenant_id))


@router.post("/brand/analyze")
def analyze(body: AnalyzeIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    data = brand_service.analyze_website(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, website_url=body.website_url)
    db.commit()
    return Envelope(data=data)


@router.put("/brand/settings")
def brand_settings(body: BrandSettingsIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    profile = brand_service.ensure_profile(db, ctx.tenant_id, ctx.user.id)
    before = {"website_url": profile.website_url, "ga4_property_id": profile.ga4_property_id}
    if body.website_url is not None:
        url = normalize_url(body.website_url) if body.website_url.strip() else ""
        if body.website_url.strip() and not url:
            raise HTTPException(status_code=422, detail="The website must be an http or https address.")
        profile.website_url = url
    if body.ga4_property_id is not None:
        value = body.ga4_property_id.strip()
        if value and not value.isdigit():
            raise HTTPException(status_code=422, detail="A GA4 property id is numeric.")
        profile.ga4_property_id = value
    write_audit(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action="growth.brand_settings", entity_type="brand_profile", entity_id=str(profile.id), before=before, after={"website_url": profile.website_url, "ga4_property_id": profile.ga4_property_id})
    db.commit()
    return Envelope(data=brand_service.brand_view(db, ctx.tenant_id))


@router.post("/brand/facts")
def add_fact(body: BrandFactIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    approve = body.approve and APPROVE in ctx.permissions
    data = brand_service.add_operator_fact(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, category=body.category, statement=body.statement, source_url=body.source_url, evidence=body.evidence, approve=approve)
    db.commit()
    return Envelope(data=data)


@router.post("/brand/facts/review")
def review_facts(body: FactReviewIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[dict]:
    data = brand_service.review_facts(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, fact_ids=body.fact_ids, decision=body.decision, note=body.note)
    db.commit()
    return Envelope(data=data)


@router.post("/brand/competitors")
def competitors(body: CompetitorsIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    if body.refresh:
        result = history.refresh_competitors(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, usernames=body.usernames or None)
    else:
        result = history.save_competitors(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, usernames=body.usernames)
    db.commit()
    return Envelope(data={"status": result["status"], "detail": result["detail"], "brand": brand_service.brand_view(db, ctx.tenant_id)})


@router.get("/accounts")
def get_accounts(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))]) -> Envelope[list[dict]]:
    return Envelope(data=[account_service.account_out(row) for row in account_service.list_accounts(db, ctx.tenant_id)])


@router.post("/accounts")
def connect(body: GrowthAccountIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    if "integrations.write" not in ctx.permissions:
        raise HTTPException(status_code=403, detail="Connecting an account needs integrations.write.")
    account = account_service.connect_account(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        platform=body.platform,
        external_id=body.external_id,
        access_token=body.access_token,
        page_id=body.page_id,
        name=body.name,
        username=body.username,
        timezone=body.timezone,
    )
    db.commit()
    return Envelope(data={"account": account_service.account_out(account), "detail": "Saved encrypted. Verify the account to read its expiry and permissions."})


@router.post("/accounts/fixture")
def fixture_account(body: FixtureAccountIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    account = account_service.create_fixture_account(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, platform=body.platform, name=body.name)
    db.commit()
    return Envelope(data={"account": account_service.account_out(account), "detail": "Fixture account. It never reaches Meta and its evidence is labeled fixture."})


@router.post("/accounts/{account_id}/verify")
def verify(account_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    data = account_service.verify_account(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, account_id=account_id)
    db.commit()
    return Envelope(data=data)


@router.patch("/accounts/{account_id}")
def update_account(account_id: UUID, body: AccountUpdateIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    windows = [window.model_dump() for window in body.posting_windows] if body.posting_windows is not None else None
    account = account_service.update_account(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, account_id=account_id, posting_windows=windows, daily_cap=body.daily_cap, timezone=body.timezone)
    db.commit()
    return Envelope(data=account_service.account_out(account))


@router.post("/accounts/{account_id}/disconnect")
def disconnect(account_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    if "integrations.write" not in ctx.permissions:
        raise HTTPException(status_code=403, detail="Disconnecting an account needs integrations.write.")
    account = account_service.disconnect_account(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, account_id=account_id)
    db.commit()
    return Envelope(data=account_service.account_out(account))


@router.post("/accounts/{account_id}/history")
def import_history(account_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    data = history.import_history(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, account_id=account_id)
    db.commit()
    return Envelope(data=data)


@router.post("/accounts/{account_id}/insights")
def collect_insights(account_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    account_result = insights.collect_account_insights(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, account_id=account_id)
    media_result = insights.collect_media_insights(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, account_id=account_id)
    db.commit()
    return Envelope(data={"account": account_result, "media": media_result})


@router.get("/strategy")
def get_strategy(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))]) -> Envelope[dict]:
    active = strategy_service.active_strategy(db, ctx.tenant_id)
    latest = strategy_service.latest_strategy(db, ctx.tenant_id)
    forms = db.scalars(select(PublicFormKey).where(PublicFormKey.tenant_id == ctx.tenant_id, PublicFormKey.status == "active", PublicFormKey.deleted_at.is_(None))).all()
    events = db.scalars(select(GrowthBusinessEvent).where(GrowthBusinessEvent.tenant_id == ctx.tenant_id, GrowthBusinessEvent.deleted_at.is_(None), GrowthBusinessEvent.status == "active").order_by(GrowthBusinessEvent.starts_on.asc())).all()
    return Envelope(
        data={
            "active": strategy_service.strategy_out(active),
            "draft": strategy_service.strategy_out(latest) if latest is not None and latest.status == "draft" else None,
            "suggested_pillars": strategy_service.suggest_pillars(db, ctx.tenant_id),
            "forms": [{"id": str(row.id), "name": row.name} for row in forms],
            "events": [strategy_service.event_out(row) for row in events],
            "review_terms_default": strategy_service.DEFAULT_REVIEW_TERMS,
        }
    )


@router.put("/strategy")
def save_strategy(body: StrategyIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    payload = body.model_dump()
    if body.review_terms is None:
        payload.pop("review_terms")
    row = strategy_service.save_strategy(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, payload=payload)
    db.commit()
    return Envelope(data=strategy_service.strategy_out(row))


@router.post("/strategy/{strategy_id}/approve")
def approve_strategy(strategy_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[dict]:
    row = strategy_service.approve_strategy(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, strategy_id=strategy_id)
    db.commit()
    return Envelope(data=strategy_service.strategy_out(row))


@router.post("/strategy/pause")
def pause_strategy(body: PauseIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[dict]:
    row = strategy_service.set_strategy_paused(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, paused=body.paused)
    db.commit()
    return Envelope(data=strategy_service.strategy_out(row))


@router.post("/events")
def add_event(body: EventIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    row = strategy_service.save_event(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, title=body.title, kind=body.kind, starts_on=body.starts_on, ends_on=body.ends_on, details=body.details, fact_ids=body.fact_ids, source_url=body.source_url)
    db.commit()
    return Envelope(data=strategy_service.event_out(row))


@router.delete("/events/{event_id}")
def remove_event(event_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    row = db.scalar(select(GrowthBusinessEvent).where(GrowthBusinessEvent.tenant_id == ctx.tenant_id, GrowthBusinessEvent.id == event_id, GrowthBusinessEvent.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    row.status = "cancelled"
    write_audit(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action="growth.event_cancel", entity_type="growth_business_event", entity_id=str(row.id), after={"status": "cancelled"})
    db.commit()
    return Envelope(data=strategy_service.event_out(row))


@router.get("/calendar")
def get_calendar(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission(READ))],
    start: str = "",
    end: str = "",
    account_id: UUID | None = None,
) -> Envelope[dict]:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        first = datetime.fromisoformat(start).replace(tzinfo=UTC) if start else today - timedelta(days=7)
        last = datetime.fromisoformat(end).replace(tzinfo=UTC) if end else today + timedelta(days=31)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Dates must be YYYY-MM-DD.") from exc
    return Envelope(data=planner.calendar_view(db, ctx.tenant_id, start=first, end=last, account_id=account_id))


@router.post("/calendar/plan")
def plan(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    data = planner.plan_rolling_calendar(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data=data)


@router.post("/calendar/{item_id}/skip")
def skip(item_id: UUID, body: SkipIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    row = planner.skip_item(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, item_id=item_id, reason=body.reason)
    db.commit()
    return Envelope(data={"id": str(row.id), "status": row.status, "blocker": row.blocker})


@router.post("/calendar/{item_id}/creative")
def produce(item_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))], force: bool = False) -> Envelope[dict]:
    try:
        data = creative_service.produce_creative(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, item_id=item_id, force=force)
    except HTTPException:
        db.commit()
        raise
    db.commit()
    return Envelope(data=data)


@router.post("/calendar/{item_id}/schedule")
def schedule(item_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[dict]:
    data = creative_service.schedule_item(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, item_id=item_id)
    db.commit()
    return Envelope(data=data)


@router.post("/calendar/{item_id}/publish")
def publish_now(item_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[dict]:
    """Runs the full gate. With publishing disabled in this deployment nothing is sent."""
    data = publisher.publish_item(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, item_id=item_id)
    db.commit()
    return Envelope(data=data)


@router.get("/creatives/review")
def review_queue(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))]) -> Envelope[list[dict]]:
    return Envelope(data=creative_service.review_queue(db, ctx.tenant_id))


@router.get("/creatives/{creative_id}")
def get_creative(creative_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))]) -> Envelope[dict]:
    return Envelope(data=creative_service.creative_view(db, ctx.tenant_id, creative_service.owned_creative(db, ctx.tenant_id, creative_id)))


@router.patch("/creatives/{creative_id}")
def revise(creative_id: UUID, body: CaptionIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    data = creative_service.revise_caption(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, creative_id=creative_id, caption=body.caption, hashtags=body.hashtags)
    db.commit()
    return Envelope(data=data)


@router.post("/creatives/{creative_id}/review")
def review_creative(creative_id: UUID, body: ReviewIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[dict]:
    data = creative_service.review_creative(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, creative_id=creative_id, decision=body.decision, note=body.note)
    db.commit()
    return Envelope(data=data)


@router.get("/publications")
def publications(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))], status: str = "") -> Envelope[list[dict]]:
    stmt = select(GrowthPublication).where(GrowthPublication.tenant_id == ctx.tenant_id, GrowthPublication.deleted_at.is_(None))
    if status:
        stmt = stmt.where(GrowthPublication.status == status)
    rows = db.scalars(stmt.order_by(GrowthPublication.created_at.desc()).limit(100)).all()
    return Envelope(data=[publisher.publication_out(row) for row in rows])


@router.post("/publications/{publication_id}/resolve")
def resolve(publication_id: UUID, body: ResolveIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[dict]:
    data = publisher.resolve_unknown(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, publication_id=publication_id, decision=body.decision, external_id=body.external_id, note=body.note)
    db.commit()
    return Envelope(data=data)


@router.get("/performance")
def performance(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission(READ))],
    range_: Annotated[str, Query(alias="range")] = "7d",
    start: str = "",
    end: str = "",
    account_id: UUID | None = None,
) -> Envelope[dict]:
    first, last = period(range_, start, end)
    return Envelope(data=insights.performance_report(db, ctx.tenant_id, start=first, end=last, account_id=account_id))


@router.get("/attribution")
def attribution(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission(READ))],
    range_: Annotated[str, Query(alias="range")] = "30d",
    start: str = "",
    end: str = "",
    account_id: UUID | None = None,
) -> Envelope[dict]:
    first, last = period(range_, start, end)
    return Envelope(data=attribution_report(db, ctx.tenant_id, start=first, end=last, account_id=account_id))


@router.post("/ga4/collect")
def ga4_collect(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[dict]:
    data = collect_ga4(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data=data)


@router.get("/grants")
def list_grants(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))]) -> Envelope[list[dict]]:
    return Envelope(data=governance.grants(db, ctx.tenant_id))


@router.post("/grants")
def create_grant(body: GrowthGrantIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[list[dict]]:
    governance.create_grant(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, platform=body.platform, volume_cap=body.volume_cap, days=body.days, name=body.name)
    db.commit()
    return Envelope(data=governance.grants(db, ctx.tenant_id))


@router.post("/grants/{grant_id}/revoke")
def revoke_grant(grant_id: UUID, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[list[dict]]:
    governance.revoke_grant(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, grant_id=grant_id)
    db.commit()
    return Envelope(data=governance.grants(db, ctx.tenant_id))


@router.get("/recommendations")
def get_recommendations(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))]) -> Envelope[list[dict]]:
    return Envelope(data=recommendations.open_recommendations(db, ctx.tenant_id))


@router.post("/recommendations/generate")
def generate_recommendations(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(WRITE))]) -> Envelope[list[dict]]:
    data = recommendations.generate(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data=data)


@router.get("/acceptance")
def acceptance_overview(db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(READ))]) -> Envelope[list[dict]]:
    return Envelope(data=acceptance_service.overview(db, ctx.tenant_id))


@router.post("/acceptance/{step_key}/authorize")
def authorize_acceptance(step_key: str, body: AcceptanceIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[dict]:
    data = acceptance_service.authorize(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, step_key=step_key, note=body.note)
    db.commit()
    return Envelope(data=data)


@router.post("/recommendations/{recommendation_id}/decide")
def decide_recommendation(recommendation_id: UUID, body: DecideIn, db: Annotated[Session, Depends(get_db)], ctx: Annotated[AuthContext, Depends(require_permission(APPROVE))]) -> Envelope[dict]:
    data = recommendations.decide(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, recommendation_id=recommendation_id, decision=body.decision)
    db.commit()
    return Envelope(data=data)
