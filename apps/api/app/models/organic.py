from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class ContentProposal(Base, TenantOwnedMixin):
    """A reviewable post that is not yet an approved creative version."""

    __tablename__ = "content_proposals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "plan_id",
            "channel",
            "topic",
            "proposed_for",
            name="uq_content_proposal_slot",
        ),
    )

    plan_id: Mapped[UUID] = mapped_column(ForeignKey("operating_plans.id"), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    audience_relevance: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    call_to_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    brief: Mapped[str] = mapped_column(Text, default="", nullable=False)
    asset_state: Mapped[str] = mapped_column(String(32), default="not_required", nullable=False)
    asset_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    asset_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    proposed_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    missing_research: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="proposed", nullable=False)
    creative_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("creative_versions.id"), nullable=True)
    context_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    context_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    public_media_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class OrganicMetricObservation(Base, TenantOwnedMixin):
    """One provider reading. A later reading replaces the same period. It is not added."""

    __tablename__ = "organic_metric_observations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "creative_version_id",
            "metric_name",
            "period_start",
            "period_end",
            name="uq_organic_metric_period",
        ),
    )

    creative_version_id: Mapped[UUID] = mapped_column(ForeignKey("creative_versions.id"), index=True, nullable=False)
    social_post_id: Mapped[UUID | None] = mapped_column(ForeignKey("social_posts.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_post_id: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    metric_name: Mapped[str] = mapped_column(String(40), nullable=False)
    definition: Mapped[str] = mapped_column(Text, default="", nullable=False)
    value_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_start: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    period_end: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    provenance: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ContentRecommendation(Base, TenantOwnedMixin):
    """A reviewable suggestion. It does not change copy, cadence, or spend."""

    __tablename__ = "content_recommendations"

    plan_id: Mapped[UUID] = mapped_column(ForeignKey("operating_plans.id"), index=True, nullable=False)
    observation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    limitation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    proposed_change: Mapped[str] = mapped_column(Text, default="", nullable=False)
    verdict: Mapped[str] = mapped_column(String(40), default="insufficient_evidence", nullable=False)
