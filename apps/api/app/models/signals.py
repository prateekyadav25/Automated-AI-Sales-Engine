from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class CustomerSignal(Base, TenantOwnedMixin):
    __tablename__ = "customer_signals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_provider",
            "external_reference",
            name="uq_customer_signal_ref",
        ),
        Index(
            "ix_customer_signals_lookup",
            "tenant_id",
            "customer_id",
            "signal_type",
            "observed_at",
        ),
    )

    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"), index=True, nullable=True)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    signal_type: Mapped[str] = mapped_column(String(80), nullable=False)
    signal_category: Mapped[str] = mapped_column(String(40), nullable=False)
    source_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    value_text: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    value_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    freshness_state: Mapped[str] = mapped_column(String(20), default="LIVE", nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)


class UsageEvent(Base, TenantOwnedMixin):
    __tablename__ = "usage_events"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "external_id", name="uq_usage_event_external"),)

    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"), index=True, nullable=True)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_external_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    feature_key: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class UsageRollup(Base, TenantOwnedMixin):
    __tablename__ = "usage_rollups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", "grain", "period_start", name="uq_usage_rollup_period"),
    )

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    grain: Mapped[str] = mapped_column(String(16), default="daily", nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dau: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wau: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mau: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    seats_licensed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seats_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
    utilization_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feature_breadth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    feature_depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trend_7d: Mapped[str] = mapped_column(String(20), default="stable", nullable=False)
    trend_30d: Mapped[str] = mapped_column(String(20), default="stable", nullable=False)
    trend_90d: Mapped[str] = mapped_column(String(20), default="stable", nullable=False)
    freshness_state: Mapped[str] = mapped_column(String(20), default="LIVE", nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SupportSnapshot(Base, TenantOwnedMixin):
    __tablename__ = "support_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", "external_id", name="uq_support_snapshot_external"),
    )

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), default="support", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    severity: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    sentiment: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reopened: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    open_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_critical: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tickets_30d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_resolution_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    escalations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freshness_state: Mapped[str] = mapped_column(String(20), default="LIVE", nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)


class FinanceSnapshot(Base, TenantOwnedMixin):
    __tablename__ = "finance_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", "external_id", name="uq_finance_snapshot_external"),
    )

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), default="finance", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    record_type: Mapped[str] = mapped_column(String(40), default="invoice", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    outstanding_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    days_past_due: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overdue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credit_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freshness_state: Mapped[str] = mapped_column(String(20), default="LIVE", nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ExternalEntityMapping(Base, TenantOwnedMixin):
    __tablename__ = "external_entity_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "entity_type", "external_id", name="uq_external_entity"),
    )

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    internal_entity_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    internal_entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationWatermark(Base, TenantOwnedMixin):
    __tablename__ = "integration_watermarks"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", name="uq_integration_watermark"),)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    last_sync_cursor: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    connected_customers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stale_customers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_syncs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CustomerIntelligenceState(Base, TenantOwnedMixin):
    __tablename__ = "customer_intelligence_states"
    __table_args__ = (UniqueConstraint("tenant_id", "customer_id", name="uq_customer_intelligence"),)

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    dirty: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dirty_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_recalc_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MLFeatureSnapshot(Base, TenantOwnedMixin):
    __tablename__ = "ml_feature_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "task_key",
            "feature_set_version",
            "as_of",
            name="uq_ml_feature_as_of",
        ),
        Index("ix_ml_feature_task", "tenant_id", "task_key", "as_of"),
    )

    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"), index=True, nullable=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="customer", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    task_key: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    features_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    source_versions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(40), default="rules-v2", nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    immutable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    correction_of_id: Mapped[UUID | None] = mapped_column(ForeignKey("ml_feature_snapshots.id"), nullable=True)


class MLOutcomeLabel(Base, TenantOwnedMixin):
    __tablename__ = "ml_outcome_labels"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "task_key",
            "label_version",
            name="uq_ml_outcome_task",
        ),
    )

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_type: Mapped[str] = mapped_column(String(40), nullable=False)
    task_key: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    label_version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False)
    label_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    label_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feature_snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("ml_feature_snapshots.id"), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
