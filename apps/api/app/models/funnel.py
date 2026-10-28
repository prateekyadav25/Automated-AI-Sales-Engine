from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class VoiceScript(Base, TenantOwnedMixin):
    __tablename__ = "voice_scripts"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), default="outbound", nullable=False)


class VoiceScriptVersion(Base, TenantOwnedMixin):
    __tablename__ = "voice_script_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "script_id", "version", name="uq_voice_script_version"),)

    script_id: Mapped[UUID] = mapped_column(ForeignKey("voice_scripts.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)


class VoiceSession(Base, TenantOwnedMixin):
    __tablename__ = "voice_sessions"

    conversation_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    approval_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_approvals.id"), nullable=True)
    carrier: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    conversation_provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    region: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    destination: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    provider_call_id: Mapped[str] = mapped_column(String(200), default="", index=True, nullable=False)
    recording_ref: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    consent_evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    ndnc_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    script_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("voice_script_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    announcement_played: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    capture_id: Mapped[UUID | None] = mapped_column(nullable=True)
    operating_plan_id: Mapped[UUID | None] = mapped_column(nullable=True)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(Text, default="", nullable=False)
    caller_identity: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    recipient_e164: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocker: Mapped[str] = mapped_column(Text, default="", nullable=False)
    operation_token: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    call_authorized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recording_authorized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    events_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    last_sequence: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    handoff_task_id: Mapped[UUID | None] = mapped_column(nullable=True)
    meeting_id: Mapped[UUID | None] = mapped_column(nullable=True)
    provider_connection_id: Mapped[UUID | None] = mapped_column(nullable=True)
    context_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    fixture: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_event: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MeetingCapture(Base, TenantOwnedMixin):
    __tablename__ = "meeting_captures"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "provider_bot_id", name="uq_meeting_capture_bot"),)

    meeting_record_id: Mapped[UUID | None] = mapped_column(ForeignKey("meeting_records.id"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    provider_bot_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    transcript_ref: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    recording_ref: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    consent_evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    meeting_url: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class AdSet(Base, TenantOwnedMixin):
    __tablename__ = "ad_sets"

    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), default="", index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    daily_budget: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    audience_id: Mapped[UUID | None] = mapped_column(nullable=True)


class AdCreative(Base, TenantOwnedMixin):
    __tablename__ = "ad_creatives"

    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"), index=True, nullable=False)
    ad_set_id: Mapped[UUID | None] = mapped_column(ForeignKey("ad_sets.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    headline: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    approval_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_approvals.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class PaidAd(Base, TenantOwnedMixin):
    """One Meta ad under a paused ad set. The tracking token is the only attribution key."""

    __tablename__ = "paid_ads"

    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"), index=True, nullable=False)
    ad_set_id: Mapped[UUID | None] = mapped_column(ForeignKey("ad_sets.id"), nullable=True)
    ad_creative_id: Mapped[UUID | None] = mapped_column(ForeignKey("ad_creatives.id"), nullable=True)
    creative_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("creative_versions.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    tracking_token: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    destination_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class AdAudience(Base, TenantOwnedMixin):
    __tablename__ = "ad_audiences"

    campaign_id: Mapped[UUID | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lookalike: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class CampaignMetricDaily(Base, TenantOwnedMixin):
    __tablename__ = "campaign_metric_daily"
    __table_args__ = (UniqueConstraint("tenant_id", "campaign_id", "metric_date", name="uq_campaign_metric_day"),)

    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"), index=True, nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    spend: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cpc: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    cpl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)


class PublicFormKey(Base, TenantOwnedMixin):
    __tablename__ = "public_form_keys"

    name: Mapped[str] = mapped_column(String(120), default="website", nullable=False)
    schema_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    token_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
