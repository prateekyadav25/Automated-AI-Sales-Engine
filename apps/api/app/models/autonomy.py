from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class AutonomousRun(Base, TenantOwnedMixin):
    __tablename__ = "autonomous_runs"

    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    trigger: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    workflow: Mapped[str] = mapped_column(String(80), default="cycle", nullable=False)
    trigger_event: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutonomousRunStep(Base, TenantOwnedMixin):
    __tablename__ = "autonomous_run_steps"

    run_id: Mapped[UUID] = mapped_column(ForeignKey("autonomous_runs.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutopilotSettings(Base, TenantOwnedMixin):
    __tablename__ = "autopilot_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_autopilot_settings_tenant"),)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_channel_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ads_channel_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    voice_channel_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    discovery_channel_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    market_monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    research_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enrichment_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    lead_scoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    qualification_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    campaign_planning_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sequence_enrollment_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    outreach_preparation_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    meeting_preparation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deal_monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    proposal_preparation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    customer_health_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    renewal_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expansion_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    advocacy_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_leads_per_day: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    email_approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    voice_approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ad_spend_approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_create_internal_tasks: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_update_scores: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    quiet_hours_start: Mapped[str] = mapped_column(String(5), default="21:00", nullable=False)
    quiet_hours_end: Mapped[str] = mapped_column(String(5), default="08:00", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    daily_budget_limit: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    monthly_budget_limit: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    minimum_lead_score: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    minimum_intent_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    minimum_expansion_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_emails_per_day: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    max_emails_per_contact_per_day: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    minimum_hours_between_outreach: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    customer_success_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    qbr_automation_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    upsell_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cross_sell_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expansion_auto_opportunity_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    renewal_windows: Mapped[str] = mapped_column(String(80), default="180,120,90,60,30", nullable=False)
    minimum_expansion_confidence: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    minimum_advocacy_score: Mapped[int] = mapped_column(Integer, default=70, nullable=False)
    max_discovery_runs_per_day: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    max_candidates_per_run: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_candidates_per_day: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    alert_rules_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    usage_freshness_hours: Mapped[int] = mapped_column(Integer, default=72, nullable=False)
    support_freshness_hours: Mapped[int] = mapped_column(Integer, default=168, nullable=False)
    finance_freshness_hours: Mapped[int] = mapped_column(Integer, default=168, nullable=False)
    high_utilization_pct: Mapped[int] = mapped_column(Integer, default=85, nullable=False)
    low_utilization_pct: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    usage_live_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    support_live_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    finance_live_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    erp_live_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_payload_retention_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    minimum_health_coverage: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    ai_daily_budget: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    max_calls_per_day: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    allow_deployment_provider_defaults: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_unscanned_uploads: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    whatsapp_channel_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_policy_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    voice_telephony_override: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    voice_conversation_provider: Mapped[str] = mapped_column(String(40), default="vapi", nullable=False)


class EntityAutomationState(Base, TenantOwnedMixin):
    __tablename__ = "entity_automation_states"
    __table_args__ = (UniqueConstraint("tenant_id", "entity_type", "entity_id", name="uq_entity_automation_state"),)

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(40), default="DISCOVERED", nullable=False)
    last_action: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    next_action: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    blocked_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("autonomous_runs.id"), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutomationIdempotencyKey(Base, TenantOwnedMixin):
    __tablename__ = "automation_idempotency_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_automation_idempotency_key"),)

    key: Mapped[str] = mapped_column(String(240), nullable=False)
    workflow: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    window: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    result_ref: Mapped[str] = mapped_column(String(64), default="", nullable=False)
