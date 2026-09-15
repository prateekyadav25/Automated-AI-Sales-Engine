"""Post-sale autopilot tables and customer lifecycle columns.

Revision ID: 007
Revises: 006
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def _add_column_if_missing(inspector, table: str, column: sa.Column) -> None:
    if table not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table)}
    if column.name in existing:
        return
    op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    inspector = inspect(bind)
    _add_column_if_missing(inspector, "customers", sa.Column("lifecycle_state", sa.String(40), server_default="NEW_CUSTOMER", nullable=False))
    _add_column_if_missing(inspector, "customers", sa.Column("owner_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "customers", sa.Column("csm_owner_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "customers", sa.Column("segment", sa.String(40), server_default="", nullable=False))
    _add_column_if_missing(inspector, "customers", sa.Column("contract_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "customers", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "customers", sa.Column("onboarding_started_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "customers", sa.Column("go_live_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "customers", sa.Column("first_value_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "customers", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "customers", sa.Column("qbr_cadence", sa.String(20), server_default="quarterly", nullable=False))
    _add_column_if_missing(inspector, "customers", sa.Column("next_qbr_at", sa.Date(), nullable=True))
    _add_column_if_missing(inspector, "customers", sa.Column("health_trend", sa.String(20), server_default="stable", nullable=False))
    _add_column_if_missing(inspector, "renewals", sa.Column("owner_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "renewals", sa.Column("contract_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "renewals", sa.Column("term_months", sa.Integer(), nullable=True))
    _add_column_if_missing(inspector, "renewals", sa.Column("stage", sa.String(40), server_default="monitoring", nullable=False))
    _add_column_if_missing(inspector, "renewals", sa.Column("readiness", sa.Integer(), server_default="0", nullable=False))
    _add_column_if_missing(inspector, "renewals", sa.Column("readiness_version", sa.String(20), server_default="rules-v1", nullable=False))
    _add_column_if_missing(inspector, "renewals", sa.Column("risk_factors_json", sa.Text(), server_default="[]", nullable=False))
    _add_column_if_missing(inspector, "renewals", sa.Column("confidence", sa.Integer(), server_default="0", nullable=False))
    _add_column_if_missing(inspector, "renewals", sa.Column("recommended_action", sa.String(200), server_default="", nullable=False))
    _add_column_if_missing(inspector, "renewals", sa.Column("baseline_amount", sa.Numeric(18, 2), nullable=True))
    _add_column_if_missing(inspector, "renewals", sa.Column("baseline_status", sa.String(40), server_default="needs_review", nullable=False))
    _add_column_if_missing(inspector, "renewals", sa.Column("last_window_days", sa.Integer(), nullable=True))
    _add_column_if_missing(inspector, "onboarding_milestones", sa.Column("owner_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "onboarding_milestones", sa.Column("position", sa.Integer(), server_default="1", nullable=False))
    _add_column_if_missing(inspector, "onboarding_milestones", sa.Column("sla_days", sa.Integer(), server_default="7", nullable=False))
    _add_column_if_missing(inspector, "onboarding_milestones", sa.Column("depends_on_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "onboarding_milestones", sa.Column("required_evidence", sa.String(200), server_default="", nullable=False))
    _add_column_if_missing(inspector, "onboarding_milestones", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "onboarding_milestones", sa.Column("template_key", sa.String(80), server_default="", nullable=False))
    _add_column_if_missing(inspector, "health_scores", sa.Column("components_json", sa.Text(), server_default="{}", nullable=False))
    _add_column_if_missing(inspector, "health_scores", sa.Column("reason_codes_json", sa.Text(), server_default="[]", nullable=False))
    _add_column_if_missing(inspector, "health_scores", sa.Column("unavailable_components", sa.String(255), server_default="", nullable=False))
    _add_column_if_missing(inspector, "health_scores", sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "health_scores", sa.Column("data_freshness", sa.String(40), server_default="", nullable=False))
    _add_column_if_missing(inspector, "health_scores", sa.Column("trend", sa.String(20), server_default="stable", nullable=False))
    _add_column_if_missing(inspector, "advocacy_assets", sa.Column("customer_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "advocacy_assets", sa.Column("advocacy_type", sa.String(40), server_default="reference", nullable=False))
    _add_column_if_missing(inspector, "advocacy_assets", sa.Column("eligibility_score", sa.Integer(), server_default="0", nullable=False))
    _add_column_if_missing(inspector, "advocacy_assets", sa.Column("ruleset_version", sa.String(20), server_default="advocacy-rules-v1", nullable=False))
    _add_column_if_missing(inspector, "advocacy_assets", sa.Column("evidence_json", sa.Text(), server_default="{}", nullable=False))
    _add_column_if_missing(inspector, "advocacy_assets", sa.Column("quote", sa.Text(), nullable=True))
    _add_column_if_missing(inspector, "referrals", sa.Column("converted_lead_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "referrals", sa.Column("source_customer_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("customer_success_enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("qbr_automation_enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("upsell_enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("cross_sell_enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("expansion_auto_opportunity_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("renewal_windows", sa.String(80), server_default="180,120,90,60,30", nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("minimum_expansion_confidence", sa.Integer(), server_default="60", nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("minimum_advocacy_score", sa.Integer(), server_default="70", nullable=False))


def downgrade() -> None:
    return
