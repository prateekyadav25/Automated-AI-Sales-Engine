from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel
from app.schemas.crm import CustomerOut


class ContractLineOut(APIModel):
    id: UUID
    product_id: UUID | None = None
    description: str = ""
    quantity: int | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class ContractOut(APIModel):
    id: UUID
    customer_id: UUID
    account_id: UUID
    opportunity_id: UUID | None = None
    status: str
    currency: str
    start_date: date | None = None
    end_date: date | None = None
    term_months: int | None = None
    total_value: Decimal | None = None
    escalation_pct: int | None = None
    lines: list[ContractLineOut] = Field(default_factory=list)


class HandoffOut(APIModel):
    id: UUID
    customer_id: UUID
    status: str
    payload: dict = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    kickoff_agenda: str = ""


class CustomerRiskOut(APIModel):
    id: UUID
    customer_id: UUID
    risk_type: str
    severity: str
    summary: str
    evidence: dict = Field(default_factory=dict)
    status: str
    detected_at: datetime | None = None
    resolved_at: datetime | None = None


class ExpansionRecOut(APIModel):
    id: UUID
    customer_id: UUID
    account_id: UUID
    product_id: UUID | None = None
    kind: str
    dimension: str
    title: str
    reason: str
    confidence: int
    amount: Decimal | None = None
    status: str
    opportunity_id: UUID | None = None
    outcome_status: str = ""
    outcome_value: Decimal | None = None
    outcome_product: str = ""


class UsageSnapshotOut(APIModel):
    id: UUID
    customer_id: UUID
    active_users: int | None = None
    seats_licensed: int | None = None
    seats_used: int | None = None
    frequency: int | None = None
    feature_breadth: int | None = None
    depth: int | None = None
    trend: str
    last_activity_at: datetime | None = None
    provider: str
    is_mock: bool
    evidence: str


class SuccessObjectiveOut(APIModel):
    id: UUID
    business_objective: str
    success_metric: str
    baseline: str | None = None
    target: str | None = None
    due_date: date | None = None
    status: str
    outcome: str = ""
    source: str = "human"


class TimelineItemOut(APIModel):
    occurred_at: datetime
    kind: str
    title: str
    entity_type: str
    entity_id: str
    source: str = ""


class TimeToValueOut(APIModel):
    days_to_kickoff: int | None = None
    days_to_go_live: int | None = None
    days_to_first_value: int | None = None
    days_to_onboarding_complete: int | None = None


class Customer360Out(APIModel):
    customer: CustomerOut
    account_name: str = ""
    lifecycle_state: str = "NEW_CUSTOMER"
    health_total: int | None = None
    health_trend: str = "stable"
    health_version: str = "rules-v2"
    health_data_coverage: int = 0
    health_components: dict = Field(default_factory=dict)
    unavailable_components: str = ""
    usage_freshness: str = "MOCK"
    support_freshness: str = "NOT_CONNECTED"
    finance_freshness: str = "NOT_CONNECTED"
    commercial_freshness: str = "LIVE"
    last_usage_at: datetime | None = None
    last_support_at: datetime | None = None
    last_finance_at: datetime | None = None
    support_open_critical: int | None = None
    finance_outstanding: str | None = None
    renewal_why_ready: list[str] = Field(default_factory=list)
    renewal_why_at_risk: list[str] = Field(default_factory=list)
    risks: list[CustomerRiskOut] = Field(default_factory=list)
    renewal_date: date | None = None
    renewal_readiness: int = 0
    renewal_countdown_days: int | None = None
    contract: ContractOut | None = None
    handoff: HandoffOut | None = None
    onboarding_status: str = ""
    milestones: list[dict] = Field(default_factory=list)
    usage: UsageSnapshotOut | None = None
    expansion: list[ExpansionRecOut] = Field(default_factory=list)
    advocacy: list[dict] = Field(default_factory=list)
    objectives: list[SuccessObjectiveOut] = Field(default_factory=list)
    automation: dict = Field(default_factory=dict)
    timeline: list[TimelineItemOut] = Field(default_factory=list)
    time_to_value: TimeToValueOut = Field(default_factory=TimeToValueOut)
    growth_plan: dict = Field(default_factory=dict)


class PostSaleAttentionOut(APIModel):
    customers_requiring_attention: int = 0
    onboarding_at_risk: int = 0
    renewals_approaching: int = 0
    renewals_at_risk: int = 0
    expansion_opportunities: int = 0
    advocacy_candidates: int = 0
    usage_risk: int = 0
    support_risk: int = 0
    commercial_risk: int = 0
    high_utilization_candidates: int = 0


class LifecycleLaneOut(APIModel):
    lane: str
    running: int = 0
    waiting: int = 0
    blocked: int = 0
    completed_today: int = 0
    failed: int = 0
