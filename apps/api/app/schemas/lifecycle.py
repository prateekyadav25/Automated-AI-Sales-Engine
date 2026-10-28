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
    operating_plan_id: UUID | None = None
    creative_version_id: UUID | None = None
    audience: str = ""
    geography: str = ""
    placements: str = ""
    timezone: str = ""
    currency: str = ""
    headline: str = ""
    body: str = ""
    call_to_action: str = ""
    asset_ref: str = ""
    destination: str = ""


class CampaignEnquiry(APIModel):
    capture_id: str
    lead_id: str = ""
    status: str = ""
    first_touch: bool = False


class CampaignOut(CampaignIn):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    last_synced_at: datetime | None = None
    assembly_status: str = ""
    assembly_blocker: str = ""
    offer_label: str = ""
    live_execution_ready: bool = False
    live_execution_note: str = ""
    activated: bool = False
    destination_url: str = ""
    schedule_label: str = ""
    ad_set_external_id: str = ""
    creative_external_id: str = ""
    ad_external_id: str = ""
    ad_set_status: str = ""
    creative_status: str = ""
    ad_status: str = ""
    enquiries: list[CampaignEnquiry] = Field(default_factory=list)


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
    operating_plan_id: UUID | None = None


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


class VoiceHandoffOut(APIModel):
    session_id: str = ""
    purpose: str = ""
    product_name: str = ""
    permission_source: str = ""
    permission_channel: str = ""
    permission_scope: str = ""
    permission_at: str = ""
    execution_authorized: bool = False
    owner_name: str = ""
    recipient: str = ""
    caller_identity: str = ""
    window_start: str = ""
    window_end: str = ""
    status: str = ""
    attempt_count: int = 0
    provider_call_id: str = ""
    fixture: bool = True
    outcome: str = ""
    last_event: str = ""
    blocker: str = ""
    recording: str = "Not authorized"
    transcript: str = "No transcript is stored."
    handoff_task_id: str = ""
    meeting_id: str = ""
    transfer: str = "Not requested"
    live_execution_ready: bool = False
    next_action: str = ""


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
    voice: VoiceHandoffOut | None = None


class MeetingIn(APIModel):
    account_id: UUID | None = None
    opportunity_id: UUID | None = None
    title: str
    occurred_at: datetime | None = None
    summary: str = ""
    next_steps: str = ""
    recording_consent: bool = False


class MeetingSlot(APIModel):
    start: str = ""
    end: str = ""
    owner_timezone: str = ""
    attendee_timezone: str = ""
    owner_local: str = ""
    attendee_local: str = ""


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
    purpose: str = ""
    lead_name: str = ""
    enquiry_note: str = ""
    product_name: str = ""
    offer_label: str = ""
    owner_name: str = ""
    calendar_id: str = ""
    owner_timezone: str = ""
    attendee_timezone: str = ""
    slots: list[MeetingSlot] = Field(default_factory=list)
    selected_slot: MeetingSlot | None = None
    booking_authorized: bool = False
    invite_authorized: bool = False
    conference_status: str = ""
    conference_id: str = ""
    join_url: str = ""
    fixture_join_url: str = ""
    fixture: bool = False
    blocker: str = ""
    availability_retrieved_at: datetime | None = None
    last_synced_at: datetime | None = None
    live_execution_ready: bool = False
    attendance: str = "Attendance is not recorded."
    next_action: str = ""
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


class DograhBrowserTestOut(APIModel):
    ready: bool
    reason: str
    voice_widget_src: str = ""
    chat_widget_src: str = ""
    sales_script: str = ""


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
    description: str = ""


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
    customer_facing_name: str = ""
    offer_label: str = ""
    sku: str = ""


class QuoteIn(APIModel):
    opportunity_id: UUID
    discount_pct: int = 0
    tax_pct: int = 0
    lines: list[QuoteLineIn] = Field(default_factory=list)
    terms: str = ""
    scope_text: str = ""
    billing_cadence: str = ""
    service_start: date | None = None
    service_end: date | None = None
    valid_until: datetime | None = None
    offer_label: str = ""


class QuoteOut(APIModel):
    id: UUID
    opportunity_id: UUID
    status: str
    discount_pct: int
    tax_pct: int
    subtotal: Decimal
    total: Decimal
    approval_required: bool
    version: int = 1
    terms: str = ""
    currency: str = ""
    customer_facing_name: str = ""
    offer_label: str = ""
    sku: str = ""
    scope_text: str = ""
    billing_cadence: str = ""
    service_start: date | None = None
    service_end: date | None = None
    valid_until: datetime | None = None
    operating_plan_id: UUID | None = None
    parent_quote_id: UUID | None = None
    superseded_by_id: UUID | None = None
    context_version: str = ""
    fixture: bool = False
    lines: list[QuoteLineOut] = Field(default_factory=list)


class CommercialViewOut(APIModel):
    opportunity_id: UUID
    account_id: UUID
    stage: str
    quote_id: UUID | None = None
    quote_version: int | None = None
    quote_status: str = ""
    currency: str = ""
    subtotal: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    discount_pct: int | None = None
    tax_pct: int | None = None
    customer_facing_name: str = ""
    offer_label: str = ""
    sku: str = ""
    scope_text: str = ""
    terms: str = ""
    billing_cadence: str = ""
    service_start: date | None = None
    service_end: date | None = None
    valid_until: datetime | None = None
    acceptance_source: str = ""
    acceptance_review: str = ""
    acceptance_relationship: str = ""
    acceptance_evidence: str = ""
    provider_verified: bool = False
    blockers: list[str] = Field(default_factory=list)
    ready: bool = False
    won: bool = False
    purchase_status: str = ""
    payment_status: str = ""
    customer_id: UUID | None = None
    customer_status: str = ""
    activated: bool = False
    onboarding_plan_id: UUID | None = None
    onboarding_status: str = ""
    onboarding_next_action: str = ""
    onboarding_blocker: str = ""
    task_id: UUID | None = None
    task_status: str = ""
    owner_id: UUID | None = None
    owner_name: str = ""
    missing_information: list[str] = Field(default_factory=list)
    fixture: bool = False
    external_block: str = ""
    external_released: bool = False
    decided_at: datetime | None = None
    reversal_reason: str = ""
    note: str = ""


class CloseWonIn(APIModel):
    quote_id: UUID
    note: str = ""


class CloseWonCorrectionIn(APIModel):
    reason: str


class PurchaseOut(APIModel):
    id: UUID
    opportunity_id: UUID
    quote_id: UUID
    quote_version: int | None = None
    status: str
    currency: str = ""
    amount: Decimal
    payment_status: str = ""
    customer_facing_name: str = ""
    sku: str = ""
    offer_label: str = ""
    scope_text: str = ""
    onboarding_status: str = ""
    onboarding_next_action: str = ""
    task_status: str = ""
    owner_name: str = ""
    fixture: bool = False
    activated: bool = False


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
