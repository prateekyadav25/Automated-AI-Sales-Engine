from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class AutonomyRunIn(APIModel):
    profile_urls: list[str] = Field(default_factory=list)


class AutonomyStepOut(APIModel):
    id: UUID
    name: str
    position: int
    status: str
    detail_json: str
    entity_type: str = ""
    entity_id: str = ""
    attempt: int = 1
    error: str = ""
    started_at: datetime | None
    finished_at: datetime | None


class AutonomyRunOut(APIModel):
    id: UUID
    tenant_id: UUID
    status: str
    trigger: str
    workflow: str = "cycle"
    trigger_event: str = ""
    correlation_id: str
    summary: str
    created_at: datetime
    finished_at: datetime | None
    steps: list[AutonomyStepOut] = Field(default_factory=list)


class AutopilotSettingsIn(APIModel):
    enabled: bool | None = None
    market_monitoring_enabled: bool | None = None
    discovery_enabled: bool | None = None
    research_enabled: bool | None = None
    enrichment_enabled: bool | None = None
    lead_scoring_enabled: bool | None = None
    qualification_enabled: bool | None = None
    campaign_planning_enabled: bool | None = None
    sequence_enrollment_enabled: bool | None = None
    outreach_preparation_enabled: bool | None = None
    meeting_preparation_enabled: bool | None = None
    deal_monitoring_enabled: bool | None = None
    proposal_preparation_enabled: bool | None = None
    customer_health_enabled: bool | None = None
    renewal_enabled: bool | None = None
    expansion_enabled: bool | None = None
    advocacy_enabled: bool | None = None
    max_leads_per_day: int | None = None
    email_approval_required: bool | None = None
    voice_approval_required: bool | None = None
    ad_spend_approval_required: bool | None = None
    auto_create_internal_tasks: bool | None = None
    auto_update_scores: bool | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str | None = None
    daily_budget_limit: float | None = None
    monthly_budget_limit: float | None = None
    minimum_lead_score: int | None = None
    minimum_intent_score: int | None = None
    minimum_expansion_score: int | None = None
    max_emails_per_day: int | None = None
    max_emails_per_contact_per_day: int | None = None
    minimum_hours_between_outreach: int | None = None
    customer_success_enabled: bool | None = None
    qbr_automation_enabled: bool | None = None
    upsell_enabled: bool | None = None
    cross_sell_enabled: bool | None = None
    expansion_auto_opportunity_enabled: bool | None = None
    renewal_windows: str | None = None
    minimum_expansion_confidence: int | None = None
    minimum_advocacy_score: int | None = None
    max_discovery_runs_per_day: int | None = None
    max_candidates_per_run: int | None = None
    max_candidates_per_day: int | None = None
    emergency_stop: bool | None = None
    email_channel_paused: bool | None = None
    ads_channel_paused: bool | None = None
    voice_channel_paused: bool | None = None
    discovery_channel_paused: bool | None = None
    usage_freshness_hours: int | None = None
    support_freshness_hours: int | None = None
    finance_freshness_hours: int | None = None
    high_utilization_pct: int | None = None
    low_utilization_pct: int | None = None
    usage_live_enabled: bool | None = None
    support_live_enabled: bool | None = None
    finance_live_enabled: bool | None = None
    erp_live_enabled: bool | None = None
    raw_payload_retention_days: int | None = None
    minimum_health_coverage: int | None = None
    ai_daily_budget: float | None = None
    max_calls_per_day: int | None = None
    allow_deployment_provider_defaults: bool | None = None
    allow_unscanned_uploads: bool | None = None
    whatsapp_channel_paused: bool | None = None


class AutopilotSettingsOut(APIModel):
    id: UUID
    enabled: bool
    market_monitoring_enabled: bool
    discovery_enabled: bool
    research_enabled: bool
    enrichment_enabled: bool
    lead_scoring_enabled: bool
    qualification_enabled: bool
    campaign_planning_enabled: bool
    sequence_enrollment_enabled: bool
    outreach_preparation_enabled: bool
    meeting_preparation_enabled: bool
    deal_monitoring_enabled: bool
    proposal_preparation_enabled: bool
    customer_health_enabled: bool
    renewal_enabled: bool
    expansion_enabled: bool
    advocacy_enabled: bool
    max_leads_per_day: int
    email_approval_required: bool
    voice_approval_required: bool
    ad_spend_approval_required: bool
    auto_create_internal_tasks: bool
    auto_update_scores: bool
    quiet_hours_start: str
    quiet_hours_end: str
    timezone: str
    daily_budget_limit: float
    monthly_budget_limit: float
    minimum_lead_score: int
    minimum_intent_score: int
    minimum_expansion_score: int
    max_emails_per_day: int = 50
    max_emails_per_contact_per_day: int = 2
    minimum_hours_between_outreach: int = 24
    customer_success_enabled: bool = True
    qbr_automation_enabled: bool = True
    upsell_enabled: bool = True
    cross_sell_enabled: bool = True
    expansion_auto_opportunity_enabled: bool = False
    renewal_windows: str = "180,120,90,60,30"
    minimum_expansion_confidence: int = 60
    minimum_advocacy_score: int = 70
    max_discovery_runs_per_day: int = 4
    max_candidates_per_run: int = 10
    max_candidates_per_day: int = 25
    emergency_stop: bool = False
    email_channel_paused: bool = False
    ads_channel_paused: bool = False
    voice_channel_paused: bool = False
    discovery_channel_paused: bool = False
    usage_freshness_hours: int = 72
    support_freshness_hours: int = 168
    finance_freshness_hours: int = 168
    high_utilization_pct: int = 85
    low_utilization_pct: int = 30
    usage_live_enabled: bool = False
    support_live_enabled: bool = False
    finance_live_enabled: bool = False
    erp_live_enabled: bool = False
    raw_payload_retention_days: int = 30
    minimum_health_coverage: int = 40
    ai_daily_budget: float = 0
    max_calls_per_day: int = 10
    allow_deployment_provider_defaults: bool = True
    allow_unscanned_uploads: bool = True
    whatsapp_channel_paused: bool = False
    current_policy_version: int = 1


class AutonomyPauseIn(APIModel):
    scope: str
    entity_id: str | None = None


class AutonomyRetryIn(APIModel):
    entity_type: str = "lead"
    entity_id: str


class ProviderHealthOut(APIModel):
    name: str
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    state: str
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error_summary: str = ""
    mode: str = ""
    pending_actions: int = 0
    failed_actions: int = 0


class AutonomyTodayOut(APIModel):
    targets_discovered: int = 0
    leads_enriched: int = 0
    leads_scored: int = 0
    leads_qualified: int = 0
    research_completed: int = 0
    messages_prepared: int = 0
    approvals_waiting: int = 0
    meetings_booked: int = 0
    opportunities_created: int = 0
    customers_at_risk: int = 0
    renewals_processed: int = 0
    expansion_opportunities: int = 0


class AutonomyStatusOut(APIModel):
    enabled: bool
    last_cycle_at: datetime | None = None
    next_cycle_at: datetime | None = None
    worker: str = ""
    queue: str = ""
    today: AutonomyTodayOut
    providers: list[ProviderHealthOut] = Field(default_factory=list)
    blocked_human: int = 0
    blocked_config: list[str] = Field(default_factory=list)
    blocked_policy: int = 0
    failed_steps: int = 0
    pending_actions: int = 0
    dead_letters: int = 0
    alerts: list[str] = Field(default_factory=list)
    scheduler_unhealthy: bool = False


class AutonomyActivityOut(APIModel):
    id: str
    occurred_at: datetime
    kind: str
    title: str
    entity_type: str
    entity_id: str
    status: str = ""


class EntityAutomationOut(APIModel):
    entity_type: str
    entity_id: str
    state: str
    last_action: str
    next_action: str
    blocked_reason: str
    paused: bool
    run_id: UUID | None = None
    workflow: str = ""
    run_status: str = ""
