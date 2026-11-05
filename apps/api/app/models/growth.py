"""Social Growth Autopilot records.

Every row is tenant-owned. A provider value keeps its source, retrieval time,
API version, and provenance. A missing value stays null. A fixture row is
never counted as live evidence.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class GrowthAccount(Base, TenantOwnedMixin):
    """One independently managed Facebook Page or Instagram professional account."""

    __tablename__ = "growth_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "platform", "external_id", name="uq_growth_account_external"),)

    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    username: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    provider_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("provider_accounts.id"), nullable=True)
    provenance: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unverified", nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_scopes: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    missing_scopes: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    capabilities: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    posting_windows: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    daily_cap: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    api_version: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    followers_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    followers_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BrandProfile(Base, TenantOwnedMixin):
    """The tenant's own brand, assembled only from stored sources."""

    __tablename__ = "brand_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_brand_profile_tenant"),)

    website_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="not_started", nullable=False)
    operating_plan_id: Mapped[UUID | None] = mapped_column(ForeignKey("operating_plans.id"), nullable=True)
    last_analysis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    analysis_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    palette_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    voice_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    logo_asset_id: Mapped[UUID | None] = mapped_column(nullable=True)
    competitor_usernames: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    ga4_property_id: Mapped[str] = mapped_column(String(40), default="", nullable=False)


class BrandSource(Base, TenantOwnedMixin):
    """One fetched page, account, or operator note that facts can cite."""

    __tablename__ = "brand_sources"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "url", name="uq_brand_source_url"),)

    profile_id: Mapped[UUID] = mapped_column(ForeignKey("brand_profiles.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provenance: Mapped[str] = mapped_column(String(20), default="live", nullable=False)


class BrandFact(Base, TenantOwnedMixin):
    """A statement with its source and review state. Claims need approval before use."""

    __tablename__ = "brand_facts"
    __table_args__ = (UniqueConstraint("tenant_id", "category", "fingerprint", name="uq_brand_fact_fingerprint"),)

    profile_id: Mapped[UUID] = mapped_column(ForeignKey("brand_profiles.id"), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("brand_sources.id"), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    method: Mapped[str] = mapped_column(String(20), default="deterministic", nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="needs_review", nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class CompetitorBenchmark(Base, TenantOwnedMixin):
    """Public business account figures the provider returned. Missing stays null."""

    __tablename__ = "competitor_benchmarks"
    __table_args__ = (UniqueConstraint("tenant_id", "platform", "username", name="uq_competitor_username"),)

    platform: Mapped[str] = mapped_column(String(20), default="instagram", nullable=False)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="not_read", nullable=False)
    followers_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posts_per_week: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    avg_likes: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    avg_comments: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    provenance: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class GrowthBusinessEvent(Base, TenantOwnedMixin):
    """An operator-recorded launch, offer, or date the calendar should consider."""

    __tablename__ = "growth_business_events"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="event", nullable=False)
    starts_on: Mapped[str] = mapped_column(String(10), nullable=False)
    ends_on: Mapped[str] = mapped_column(String(10), nullable=False)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)
    fact_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class GrowthStrategy(Base, TenantOwnedMixin):
    """The client-approved plan that automation may follow. Edits create a new version."""

    __tablename__ = "growth_strategies"
    __table_args__ = (UniqueConstraint("tenant_id", "version", name="uq_growth_strategy_version"),)

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    operating_plan_id: Mapped[UUID | None] = mapped_column(ForeignKey("operating_plans.id"), nullable=True)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    optimization_metric: Mapped[str] = mapped_column(String(40), default="reach", nullable=False)
    pillars_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    audiences_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    cadence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    call_to_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    destination_kind: Mapped[str] = mapped_column(String(20), default="form", nullable=False)
    destination_form_key_id: Mapped[UUID | None] = mapped_column(ForeignKey("public_form_keys.id"), nullable=True)
    destination_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    auto_create: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_schedule: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_terms_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GrowthCalendarItem(Base, TenantOwnedMixin):
    """One planned slot for one account. The brief records why it exists."""

    __tablename__ = "growth_calendar_items"
    __table_args__ = (UniqueConstraint("tenant_id", "account_id", "slot_key", name="uq_growth_calendar_slot"),)

    strategy_id: Mapped[UUID] = mapped_column(ForeignKey("growth_strategies.id"), index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("growth_accounts.id"), index=True, nullable=False)
    slot_key: Mapped[str] = mapped_column(String(80), nullable=False)
    planned_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    local_date: Mapped[str] = mapped_column(String(10), nullable=False)
    pillar_key: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    audience: Mapped[str] = mapped_column(Text, default="", nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    call_to_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("growth_business_events.id"), nullable=True)
    brief_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="planned", nullable=False)
    blocker: Mapped[str] = mapped_column(Text, default="", nullable=False)
    creative_id: Mapped[UUID | None] = mapped_column(nullable=True)
    publication_id: Mapped[UUID | None] = mapped_column(nullable=True)
    tracking_link_id: Mapped[UUID | None] = mapped_column(nullable=True)


class GrowthCreative(Base, TenantOwnedMixin):
    """A caption and its assets for one calendar item. An edit creates a new version."""

    __tablename__ = "growth_creatives"
    __table_args__ = (UniqueConstraint("tenant_id", "calendar_item_id", "version", name="uq_growth_creative_version"),)

    calendar_item_id: Mapped[UUID] = mapped_column(ForeignKey("growth_calendar_items.id"), index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("growth_accounts.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="", nullable=False)
    hashtags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    alt_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    call_to_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    link_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    fact_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    claims_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    generation: Mapped[str] = mapped_column(String(20), default="deterministic", nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    review_reasons_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    quality_state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    quality_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="", nullable=False)


class GrowthAsset(Base, TenantOwnedMixin):
    """Rendered or uploaded media. Provenance decides whether it can be commercial."""

    __tablename__ = "growth_assets"

    creative_id: Mapped[UUID | None] = mapped_column(ForeignKey("growth_creatives.id"), index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mime: Mapped[str] = mapped_column(String(40), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    object_key: Mapped[str] = mapped_column(String(400), nullable=False)
    social_image_id: Mapped[UUID | None] = mapped_column(nullable=True)
    public_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    template: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    provenance: Mapped[str] = mapped_column(String(24), default="rendered", nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    quality_state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    quality_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class GrowthPublication(Base, TenantOwnedMixin):
    """One provider attempt for one approved creative. Container ids are kept for reconciliation."""

    __tablename__ = "growth_publications"
    __table_args__ = (UniqueConstraint("tenant_id", "calendar_item_id", "creative_id", name="uq_growth_publication_creative"),)

    calendar_item_id: Mapped[UUID] = mapped_column(ForeignKey("growth_calendar_items.id"), index=True, nullable=False)
    creative_id: Mapped[UUID] = mapped_column(ForeignKey("growth_creatives.id"), nullable=False)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("growth_accounts.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="requested", nullable=False)
    effect_key: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    container_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    child_container_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    upload_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    permalink: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_class: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    api_version: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    provenance: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    caption_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    request_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    response_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)


class GrowthMedia(Base, TenantOwnedMixin):
    """A post on an authorized account, read back or published by this engine."""

    __tablename__ = "growth_media"
    __table_args__ = (UniqueConstraint("tenant_id", "account_id", "external_id", name="uq_growth_media_external"),)

    account_id: Mapped[UUID] = mapped_column(ForeignKey("growth_accounts.id"), index=True, nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="historical", nullable=False)
    publication_id: Mapped[UUID | None] = mapped_column(nullable=True)
    media_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    media_product_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="", nullable=False)
    permalink: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provenance: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    pillar_key: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    format: Mapped[str] = mapped_column(String(20), default="", nullable=False)


class GrowthMetricObservation(Base, TenantOwnedMixin):
    """One provider reading. A later reading of the same period replaces it. Readings are never added."""

    __tablename__ = "growth_metric_observations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "scope",
            "external_id",
            "metric",
            "period",
            "period_key",
            name="uq_growth_metric_reading",
        ),
    )

    account_id: Mapped[UUID] = mapped_column(ForeignKey("growth_accounts.id"), index=True, nullable=False)
    media_id: Mapped[UUID | None] = mapped_column(ForeignKey("growth_media.id"), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    period_key: Mapped[str] = mapped_column(String(40), nullable=False)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    api_version: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    endpoint: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    provenance: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class GrowthTrackingLink(Base, TenantOwnedMixin):
    """A canonical link for one planned post. The token attributes a later enquiry."""

    __tablename__ = "growth_tracking_links"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    calendar_item_id: Mapped[UUID | None] = mapped_column(ForeignKey("growth_calendar_items.id"), nullable=True)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("growth_accounts.id"), nullable=True)
    destination_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    form_key_id: Mapped[UUID | None] = mapped_column(nullable=True)
    utm_source: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    utm_medium: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    utm_campaign: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    utm_content: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class GrowthLinkClick(Base, TenantOwnedMixin):
    """A first-party redirect. No address or browser fingerprint is stored."""

    __tablename__ = "growth_link_clicks"

    link_id: Mapped[UUID] = mapped_column(ForeignKey("growth_tracking_links.id"), index=True, nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    referrer_host: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class GrowthTrafficObservation(Base, TenantOwnedMixin):
    """A GA4 Data API row. Missing metrics stay null."""

    __tablename__ = "growth_traffic_observations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "property_id", "day", "source", "medium", "campaign", name="uq_growth_traffic_row"),
    )

    property_id: Mapped[str] = mapped_column(String(40), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    medium: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    campaign: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    sessions: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_users: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    key_events: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="recorded", nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class GrowthRecommendation(Base, TenantOwnedMixin):
    """A reviewable suggestion. It never changes the strategy, the copy, or spend by itself."""

    __tablename__ = "growth_recommendations"

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    observation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    limitation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    proposed_change: Mapped[str] = mapped_column(Text, default="", nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), default="insufficient_evidence", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
