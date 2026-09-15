from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel
from app.schemas.crm import CustomerOut


class CampaignIn(APIModel):
    name: str
    channel: str = "outbound"
    status: str = "draft"
    objective: str = "pipeline"
    budget: Decimal = Decimal("0")
    spent: Decimal = Decimal("0")
    start_date: date | None = None
    end_date: date | None = None
    notes: str = ""
    external_campaign_id: str = ""
    provider: str = ""
    provider_status: str = ""
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    ctr: Decimal | None = None
    cpc: Decimal | None = None
    cpl: Decimal | None = None


class CampaignOut(CampaignIn):
    id: UUID
    tenant_id: UUID
    created_at: datetime


class CampaignMemberIn(APIModel):
    account_id: UUID | None = None
    lead_id: UUID | None = None
    status: str = "targeted"


class CampaignMemberOut(CampaignMemberIn):
    id: UUID
    campaign_id: UUID


class CampaignDetail(CampaignOut):
    members: list[CampaignMemberOut] = Field(default_factory=list)


class AbmIn(APIModel):
    account_id: UUID
    name: str
    thesis: str = ""
    status: str = "planned"


class AbmOut(AbmIn):
    id: UUID
    created_at: datetime


class SequenceStepIn(APIModel):
    position: int = 1
    delay_days: int = 0
    action_type: str = "email_draft"
    template: str = ""


class SequenceStepOut(SequenceStepIn):
    id: UUID
    sequence_id: UUID


class SequenceIn(APIModel):
    name: str
    channel: str = "email"
    status: str = "draft"
    purpose: str = "sdr"
    steps: list[SequenceStepIn] = Field(default_factory=list)


class SequenceOut(APIModel):
    id: UUID
    name: str
    channel: str
    status: str
    purpose: str
    created_at: datetime


class SequenceDetail(SequenceOut):
    steps: list[SequenceStepOut] = Field(default_factory=list)


class EnrollIn(APIModel):
    lead_id: UUID


class EnrollmentOut(APIModel):
    id: UUID
    sequence_id: UUID
    lead_id: UUID
    status: str
    current_step: int
    next_run_at: datetime | None


class ConversationIn(APIModel):
    channel: str = "chat"
    account_id: UUID | None = None
    contact_id: UUID | None = None
    subject: str = ""
    outcome: str = ""
    sentiment: str = "neutral"
    consent: bool = False
    transcript: str = ""
    summary: str = ""


class EmailMessageOut(APIModel):
    id: UUID
    direction: str
    from_addr: str
    to_addrs: str
    subject: str
    body_text: str
    provider: str
    provider_message_id: str
    provider_thread_id: str
    status: str
    classification: str = ""
    sent_at: datetime | None = None
    received_at: datetime | None = None
    created_at: datetime


class ConversationOut(ConversationIn):
    id: UUID
    status: str
    provider: str
    is_mock: bool
    created_at: datetime
    lead_id: UUID | None = None
    provider_thread_id: str = ""
    call_status: str = ""
    messages: list[EmailMessageOut] = Field(default_factory=list)


class MeetingIn(APIModel):
    account_id: UUID | None = None
    opportunity_id: UUID | None = None
    title: str
    occurred_at: datetime | None = None
    summary: str = ""
    next_steps: str = ""
    recording_consent: bool = False


class MeetingOut(MeetingIn):
    id: UUID
    provider: str
    is_mock: bool
    created_at: datetime
    lead_id: UUID | None = None
    contact_id: UUID | None = None
    owner_id: UUID | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str = "UTC"
    status: str = "logged"
    provider_event_id: str | None = None
    calendar_account: str = ""
    recording_consent: bool = False
    transcript: str = ""
    insights_json: str = "{}"
    captures: list["MeetingCaptureOut"] = Field(default_factory=list)


class MeetingCaptureOut(APIModel):
    id: UUID
    meeting_record_id: UUID | None = None
    provider: str
    provider_bot_id: str = ""
    status: str
    meeting_url: str = ""
    last_error: str = ""


class MeetingCaptureIn(APIModel):
    meeting_url: str = ""


class MeetingTranscriptIn(APIModel):
    transcript: str


class VoiceScriptIn(APIModel):
    name: str
    purpose: str = "outbound"
    body: str = ""


class VoiceScriptVersionOut(APIModel):
    id: UUID
    version: int
    body: str
    status: str


class VoiceScriptOut(APIModel):
    id: UUID
    name: str
    status: str
    current_version: int
    purpose: str
    versions: list[VoiceScriptVersionOut] = Field(default_factory=list)


class CampaignLaunchOut(APIModel):
    approval_id: UUID
    campaign_id: UUID
    status: str


class VoiceDialIn(APIModel):
    contact_id: UUID
    consent: bool = False


class VoiceDialOut(APIModel):
    approval_id: UUID
    status: str


class MeetingExtractIn(APIModel):
    title: str = "Extracted meeting notes"
    transcript: str
    account_id: UUID | None = None
    opportunity_id: UUID | None = None


class DealInsightOut(APIModel):
    id: UUID
    opportunity_id: UUID
    opportunity_name: str = ""
    risk_score: int
    missing_buyer: bool
    weak_champion: bool
    stall: bool
    close_slip: bool
    competitor_risk: bool
    missing_next_step: bool
    reasons: str
    version: str


class ProductIn(APIModel):
    sku: str
    name: str
    kind: str = "subscription"
    list_price: Decimal = Decimal("0")
    currency: str = "INR"


class ProductOut(ProductIn):
    id: UUID


class QuoteLineIn(APIModel):
    product_id: UUID
    quantity: int = 1
    unit_price: Decimal | None = None


class QuoteLineOut(APIModel):
    id: UUID
    quote_id: UUID
    product_id: UUID
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class QuoteIn(APIModel):
    opportunity_id: UUID
    discount_pct: int = 0
    tax_pct: int = 0
    lines: list[QuoteLineIn] = Field(default_factory=list)


class QuoteOut(APIModel):
    id: UUID
    opportunity_id: UUID
    status: str
    discount_pct: int
    tax_pct: int
    subtotal: Decimal
    total: Decimal
    approval_required: bool
    lines: list[QuoteLineOut] = Field(default_factory=list)


class ForecastOut(APIModel):
    id: UUID
    period: str
    committed: Decimal
    best_case: Decimal
    pipeline: Decimal
    weighted: Decimal
    win_rate: float
    version: str
    created_at: datetime


class HealthOut(APIModel):
    id: UUID
    customer_id: UUID
    total: int
    adoption: int
    usage: int
    engagement: int
    commercial: int
    relationship: int
    onboarding: int
    reasons: str
    version: str
    unavailable_components: str = ""
    trend: str = "stable"
    data_freshness: str = ""
    health_data_coverage: int = 0


class MilestoneOut(APIModel):
    id: UUID
    title: str
    due_date: date | None
    status: str


class SuccessRow(APIModel):
    customer: CustomerOut
    account_id: UUID
    account_name: str
    health: HealthOut | None = None
    onboarding_status: str = ""
    milestones: list[MilestoneOut] = Field(default_factory=list)
    renewal_date: date | None = None
    arr: Decimal = Decimal("0")


class RenewalOut(APIModel):
    id: UUID
    customer_id: UUID
    account_id: UUID
    account_name: str = ""
    renewal_date: date | None
    current_arr: Decimal
    status: str
    readiness: int = 0
    recommended_action: str = ""
    baseline_amount: Decimal | None = None
    baseline_status: str = "needs_review"
    stage: str = "monitoring"
    why_ready: list[str] = Field(default_factory=list)
    why_at_risk: list[str] = Field(default_factory=list)


class WhitespaceOut(APIModel):
    id: UUID
    account_id: UUID
    account_name: str = ""
    product_id: UUID
    product_name: str = ""
    status: str
    propensity: int
    value_hint: Decimal


class AdvocacyIn(APIModel):
    account_id: UUID
    kind: str = "reference"
    readiness: int = 0
    status: str = "identified"
    notes: str = ""


class AdvocacyOut(AdvocacyIn):
    id: UUID
    customer_id: UUID | None = None
    advocacy_type: str = "reference"
    eligibility_score: int = 0
    quote: str | None = None
    ruleset_version: str = "advocacy-rules-v1"


class ReferralIn(APIModel):
    referrer_account_id: UUID
    referred_name: str
    email: str = ""
    status: str = "new"


class ReferralOut(ReferralIn):
    id: UUID


class ModelCardOut(APIModel):
    id: UUID
    name: str
    purpose: str
    version: str
    status: str
    notes: str
    last_trained: datetime | None = None
    task_key: str = ""
    algorithm: str = "rules"
    dataset_version: str = ""
    metrics_json: str | None = None
    limitations: str = ""


class PlaybookIn(APIModel):
    name: str
    trigger_event: str
    autonomy_level: int = 1
    actions_json: str = "[]"
    is_active: bool = True


class PlaybookOut(PlaybookIn):
    id: UUID


class PlaybookRunIn(APIModel):
    entity_type: str
    entity_id: str


class WorkflowRunOut(APIModel):
    id: UUID
    trigger_event: str
    status: str
    log_json: str
    finished_at: datetime | None
    created_at: datetime


class LifecycleOverview(APIModel):
    campaigns: int
    sequences: int
    enrollments: int
    conversations: int
    meetings: int
    open_quotes: int
    at_risk_deals: int
    customers: int
    at_risk_health: int
    renewals_due_90: int
    whitespace: int
    advocacy: int
    playbook_runs: int
    arr: str
    note: str = "SQL counts only. Empty stays empty."


class AccountLifecycleOut(APIModel):
    meetings: list[MeetingOut] = Field(default_factory=list)
    quotes: list[QuoteOut] = Field(default_factory=list)
    insights: list[DealInsightOut] = Field(default_factory=list)
    whitespace: list[WhitespaceOut] = Field(default_factory=list)
    advocacy: list[AdvocacyOut] = Field(default_factory=list)
    customer: CustomerOut | None = None
    health: HealthOut | None = None
    renewal: RenewalOut | None = None
