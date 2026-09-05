from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class Account(Base, TenantOwnedMixin):
    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    website: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    domain: Mapped[str] = mapped_column(String(255), default="", index=True, nullable=False)
    hq_country: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annual_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ownership: Mapped[str] = mapped_column(String(40), default="prospect", nullable=False)
    target_tier: Mapped[str] = mapped_column(String(20), default="tier_2", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Contact(Base, TenantOwnedMixin):
    __tablename__ = "contacts"

    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    seniority: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    department: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    buying_role: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    consent_email: Mapped[bool] = mapped_column(default=False, nullable=False)
    opt_out: Mapped[bool] = mapped_column(default=False, nullable=False)


class ICP(Base, TenantOwnedMixin):
    __tablename__ = "icps"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    industries: Mapped[str] = mapped_column(Text, default="", nullable=False)
    geographies: Mapped[str] = mapped_column(Text, default="", nullable=False)
    min_employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)


class Lead(Base, TenantOwnedMixin):
    __tablename__ = "leads"

    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", index=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="manual", nullable=False)
    channel: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    campaign: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    utm_source: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="new", nullable=False)
    consent_email: Mapped[bool] = mapped_column(default=False, nullable=False)
    opt_out: Mapped[bool] = mapped_column(default=False, nullable=False)
    intent_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_buying_trigger: Mapped[bool] = mapped_column(default=False, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class LeadScore(Base, TenantOwnedMixin):
    __tablename__ = "lead_scores"

    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    icp_fit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    intent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    persona: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    company_potential: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    buying_trigger: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timing: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reasons: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="rules-v1", nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=80, nullable=False)


class Opportunity(Base, TenantOwnedMixin):
    __tablename__ = "opportunities"

    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), default="qualification", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    probability: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    expected_close: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_step: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    loss_reason: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Task(Base, TenantOwnedMixin):
    __tablename__ = "tasks"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="human", nullable=False)


class Activity(Base, TenantOwnedMixin):
    __tablename__ = "activities"

    entity_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    activity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), default="human", nullable=False)


class Customer(Base, TenantOwnedMixin):
    __tablename__ = "customers"

    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    opportunity_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="onboarding", nullable=False)
    arr: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)


class Renewal(Base, TenantOwnedMixin):
    __tablename__ = "renewals"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_arr: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="stub", nullable=False)


class NextBestAction(Base, TenantOwnedMixin):
    __tablename__ = "next_best_actions"

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=70, nullable=False)
    expected_impact: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
