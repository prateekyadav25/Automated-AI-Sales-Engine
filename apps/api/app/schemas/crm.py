from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class AccountIn(APIModel):
    name: str
    industry: str = ""
    website: str = ""
    domain: str = ""
    hq_country: str = ""
    employee_count: int | None = None
    annual_revenue: Decimal | None = None
    ownership: str = "prospect"
    target_tier: str = "tier_2"
    notes: str = ""


class AccountOut(AccountIn):
    id: UUID
    tenant_id: UUID
    created_at: datetime


class ContactIn(APIModel):
    account_id: UUID | None = None
    first_name: str
    last_name: str
    email: str = ""
    phone: str = ""
    title: str = ""
    seniority: str = ""
    department: str = ""
    buying_role: str = ""
    consent_email: bool = False
    opt_out: bool = False


class ContactOut(ContactIn):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    account_name: str | None = None


class LeadIn(APIModel):
    account_id: UUID | None = None
    contact_id: UUID | None = None
    first_name: str
    last_name: str
    email: str = ""
    company_name: str = ""
    title: str = ""
    source: str = "manual"
    channel: str = ""
    campaign: str = ""
    utm_source: str = ""
    status: str = "new"
    consent_email: bool = False
    opt_out: bool = False
    intent_score: int = 0
    engagement_score: int = 0
    has_buying_trigger: bool = False
    notes: str = ""


class LeadScoreOut(APIModel):
    id: UUID
    lead_id: UUID
    total: int
    icp_fit: int
    intent: int
    engagement: int
    persona: int
    company_potential: int
    buying_trigger: int
    timing: int
    reasons: str
    version: str
    confidence: int
    created_at: datetime


class LeadOut(LeadIn):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    latest_score: LeadScoreOut | None = None


class OpportunityIn(APIModel):
    account_id: UUID
    name: str
    stage: str = "qualification"
    amount: Decimal = Decimal("0")
    probability: int = Field(default=10, ge=0, le=100)
    expected_close: date | None = None
    next_step: str = ""
    owner_id: UUID | None = None


class OpportunityOut(OpportunityIn):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    loss_reason: str = ""


class TaskIn(APIModel):
    title: str
    description: str = ""
    status: str = "open"
    priority: str = "medium"
    due_at: datetime | None = None
    owner_id: UUID | None = None
    entity_type: str = ""
    entity_id: str = ""
    source: str = "human"


class TaskOut(TaskIn):
    id: UUID
    tenant_id: UUID
    created_at: datetime


class ActivityOut(APIModel):
    id: UUID
    entity_type: str
    entity_id: str
    activity_type: str
    title: str
    body: str
    actor_type: str
    created_at: datetime


class ICPIn(APIModel):
    name: str
    industries: str = ""
    geographies: str = ""
    min_employees: int | None = None
    max_employees: int | None = None
    description: str = ""
    is_default: bool = False


class ICPOut(ICPIn):
    id: UUID
    tenant_id: UUID


class CustomerOut(APIModel):
    id: UUID
    account_id: UUID
    opportunity_id: UUID | None
    status: str
    arr: Decimal
    account_name: str | None = None


class NBAOut(APIModel):
    id: UUID
    entity_type: str
    entity_id: str
    action: str
    reason: str
    priority: str
    confidence: int
    expected_impact: str
    status: str


class KPIOut(APIModel):
    total_leads: int
    mql_count: int
    sql_count: int
    total_accounts: int
    open_opportunities: int
    won_opportunities: int
    open_pipeline_value: Decimal
    weighted_pipeline_value: Decimal
    win_rate: float
    tasks_open: int
    tasks_overdue: int
    pending_approvals: int
    knowledge_sources: int


class StageMixOut(APIModel):
    stage: str
    count: int
    amount: Decimal


class SearchHit(APIModel):
    entity_type: str
    id: UUID
    title: str
    subtitle: str


class SearchOut(APIModel):
    hits: list[SearchHit]


class ImportPreviewIn(APIModel):
    entity: str
    csv_text: str


class ImportPreviewOut(APIModel):
    entity: str
    columns: list[str]
    rows: list[dict]
    errors: list[str]
    count: int


class ImportCommitIn(APIModel):
    entity: str
    rows: list[dict]


class AccountContextOut(APIModel):
    account: AccountOut
    contacts: list[ContactOut]
    opportunities: list[OpportunityOut]
    tasks: list[TaskOut]
    lifecycle: dict | None = None
