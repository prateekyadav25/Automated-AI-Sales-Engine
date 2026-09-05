from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class Campaign(Base, TenantOwnedMixin):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), default="outbound", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    objective: Mapped[str] = mapped_column(String(80), default="pipeline", nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    spent: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class CampaignMember(Base, TenantOwnedMixin):
    __tablename__ = "campaign_members"

    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"), index=True, nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="targeted", nullable=False)


class AbmPlay(Base, TenantOwnedMixin):
    __tablename__ = "abm_plays"

    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="planned", nullable=False)


class Sequence(Base, TenantOwnedMixin):
    __tablename__ = "sequences"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), default="email", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), default="sdr", nullable=False)


class SequenceStep(Base, TenantOwnedMixin):
    __tablename__ = "sequence_steps"

    sequence_id: Mapped[UUID] = mapped_column(ForeignKey("sequences.id"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), default="email_draft", nullable=False)
    template: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SequenceEnrollment(Base, TenantOwnedMixin):
    __tablename__ = "sequence_enrollments"

    sequence_id: Mapped[UUID] = mapped_column(ForeignKey("sequences.id"), index=True, nullable=False)
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(Base, TenantOwnedMixin):
    __tablename__ = "conversations"

    channel: Mapped[str] = mapped_column(String(20), default="chat", nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    subject: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral", nullable=False)
    consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="mock-voice", nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    transcript: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)


class MeetingRecord(Base, TenantOwnedMixin):
    __tablename__ = "meeting_records"

    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    opportunity_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    next_steps: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="human", nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DealInsight(Base, TenantOwnedMixin):
    __tablename__ = "deal_insights"

    opportunity_id: Mapped[UUID] = mapped_column(ForeignKey("opportunities.id"), index=True, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_buyer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    weak_champion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stall: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    close_slip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    competitor_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    missing_next_step: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reasons: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="rules-v1", nullable=False)


class Product(Base, TenantOwnedMixin):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="subscription", nullable=False)
    list_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)


class Quote(Base, TenantOwnedMixin):
    __tablename__ = "quotes"

    opportunity_id: Mapped[UUID] = mapped_column(ForeignKey("opportunities.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    discount_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tax_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class QuoteLine(Base, TenantOwnedMixin):
    __tablename__ = "quote_lines"

    quote_id: Mapped[UUID] = mapped_column(ForeignKey("quotes.id"), index=True, nullable=False)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)


class ForecastSnapshot(Base, TenantOwnedMixin):
    __tablename__ = "forecast_snapshots"

    period: Mapped[str] = mapped_column(String(20), nullable=False)
    committed: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    best_case: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    pipeline: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    weighted: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    win_rate: Mapped[float] = mapped_column(Numeric(8, 4), default=0, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="rules-v1", nullable=False)


class OnboardingPlan(Base, TenantOwnedMixin):
    __tablename__ = "onboarding_plans"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="planned", nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)


class OnboardingMilestone(Base, TenantOwnedMixin):
    __tablename__ = "onboarding_milestones"

    plan_id: Mapped[UUID] = mapped_column(ForeignKey("onboarding_plans.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)


class SuccessPlan(Base, TenantOwnedMixin):
    __tablename__ = "success_plans"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class HealthScore(Base, TenantOwnedMixin):
    __tablename__ = "health_scores"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    adoption: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    commercial: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relationship: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    onboarding: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reasons: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="rules-v1", nullable=False)


class WhitespaceCell(Base, TenantOwnedMixin):
    __tablename__ = "whitespace_cells"

    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="no_penetration", nullable=False)
    propensity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    value_hint: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)


class AdvocacyAsset(Base, TenantOwnedMixin):
    __tablename__ = "advocacy_assets"

    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="reference", nullable=False)
    readiness: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="identified", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Referral(Base, TenantOwnedMixin):
    __tablename__ = "referrals"

    referrer_account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    referred_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)


class ModelCard(Base, TenantOwnedMixin):
    __tablename__ = "model_cards"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="rules-v1", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="production_rules", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Playbook(Base, TenantOwnedMixin):
    __tablename__ = "playbooks"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    trigger_event: Mapped[str] = mapped_column(String(80), nullable=False)
    autonomy_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    actions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
