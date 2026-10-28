from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class OperatingPlan(Base, TenantOwnedMixin):
    __tablename__ = "operating_plans"

    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"), index=True, nullable=True)
    campaign_id: Mapped[UUID | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    form_key_id: Mapped[UUID | None] = mapped_column(ForeignKey("public_form_keys.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="linkedin", nullable=False)
    audience: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    research_limit: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    research_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocker: Mapped[str] = mapped_column(Text, default="", nullable=False)
    next_action: Mapped[str] = mapped_column(String(80), default="start_operating_plan", nullable=False)
    context_snapshot: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_brief_json: Mapped[str] = mapped_column(Text, default="", nullable=False)


class CreativeVersion(Base, TenantOwnedMixin):
    __tablename__ = "creative_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "plan_id", "channel", "version_number", name="uq_creative_version"),
    )

    plan_id: Mapped[UUID] = mapped_column(ForeignKey("operating_plans.id"), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    headline: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    social_post_id: Mapped[UUID | None] = mapped_column(nullable=True)
    provider_ref: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    permalink: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    publication_token: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, default="", nullable=False)


class DemoScope(Base, TenantOwnedMixin):
    """Narrow external-action boundary for one controlled demonstration."""

    __tablename__ = "demo_scopes"

    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    plan_id: Mapped[UUID | None] = mapped_column(ForeignKey("operating_plans.id"), nullable=True)
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("creative_versions.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    buyer_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    sender_mailbox: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    action_limit: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="prepared", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quiet_hours_start: Mapped[str] = mapped_column(String(5), default="21:00", nullable=False)
    quiet_hours_end: Mapped[str] = mapped_column(String(5), default="08:00", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    form_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    page_ref: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    page_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    calendar_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    allowed_actions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    binding_digest: Mapped[str] = mapped_column(String(64), default="", nullable=False)
