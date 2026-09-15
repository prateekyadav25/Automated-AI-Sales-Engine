from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class Contract(Base, TenantOwnedMixin):
    __tablename__ = "contracts"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    opportunity_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    quote_id: Mapped[UUID | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="closed_won", nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    escalation_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ContractLine(Base, TenantOwnedMixin):
    __tablename__ = "contract_lines"

    contract_id: Mapped[UUID] = mapped_column(ForeignKey("contracts.id"), index=True, nullable=False)
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class HandoffPackage(Base, TenantOwnedMixin):
    __tablename__ = "handoff_packages"
    __table_args__ = (UniqueConstraint("tenant_id", "customer_id", name="uq_handoff_customer"),)

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    opportunity_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    missing_fields_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    risks_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    kickoff_agenda: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class OnboardingTemplate(Base, TenantOwnedMixin):
    __tablename__ = "onboarding_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_onboarding_template_key"),)

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    segment: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    industry: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)


class OnboardingTemplateItem(Base, TenantOwnedMixin):
    __tablename__ = "onboarding_template_items"

    template_id: Mapped[UUID] = mapped_column(ForeignKey("onboarding_templates.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), default="IMPLEMENTATION", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    offset_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    sla_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    owner_role: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    depends_on_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_evidence: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    task_title: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class SuccessPlanObjective(Base, TenantOwnedMixin):
    __tablename__ = "success_plan_objectives"

    plan_id: Mapped[UUID] = mapped_column(ForeignKey("success_plans.id"), index=True, nullable=False)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    business_objective: Mapped[str] = mapped_column(String(200), nullable=False)
    success_metric: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    baseline: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target: Mapped[str | None] = mapped_column(String(80), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="proposed", nullable=False)
    outcome: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="human", nullable=False)


class HealthScoreSnapshot(Base, TenantOwnedMixin):
    __tablename__ = "health_score_snapshots"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    components_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    unavailable_components: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(20), default="rules-v1", nullable=False)
    data_freshness: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    trend: Mapped[str] = mapped_column(String(20), default="stable", nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_data_coverage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CustomerRisk(Base, TenantOwnedMixin):
    __tablename__ = "customer_risks"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    risk_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(20), default="churn-rules-v1", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductUsageSnapshot(Base, TenantOwnedMixin):
    __tablename__ = "product_usage_snapshots"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seats_licensed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seats_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frequency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feature_breadth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trend: Mapped[str] = mapped_column(String(20), default="stable", nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), default="mock-usage", nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ProductRelationship(Base, TenantOwnedMixin):
    __tablename__ = "product_relationships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "related_product_id", "relationship", name="uq_product_relationship"),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    related_product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    relationship: Mapped[str] = mapped_column(String(40), default="complementary", nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ExpansionRecommendation(Base, TenantOwnedMixin):
    __tablename__ = "expansion_recommendations"

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="expansion", nullable=False)
    dimension: Mapped[str] = mapped_column(String(40), default="product", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ruleset_version: Mapped[str] = mapped_column(String(20), default="rules-v1", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    opportunity_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    outcome_status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    outcome_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    outcome_product: Mapped[str] = mapped_column(String(120), default="", nullable=False)


class AIArtifact(Base, TenantOwnedMixin):
    __tablename__ = "ai_artifacts"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "entity_type", "entity_id", name="uq_ai_artifact_entity"),)

    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    content_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
