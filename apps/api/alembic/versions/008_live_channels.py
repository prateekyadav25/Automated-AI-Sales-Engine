"""Live channel execution columns and provider ops tables.

Revision ID: 008
Revises: 007
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "008"
down_revision = "007"
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
    _add_column_if_missing(inspector, "icps", sa.Column("personas", sa.Text(), server_default="", nullable=False))
    _add_column_if_missing(inspector, "icps", sa.Column("seniorities", sa.Text(), server_default="", nullable=False))
    _add_column_if_missing(inspector, "icps", sa.Column("job_functions", sa.Text(), server_default="", nullable=False))
    _add_column_if_missing(inspector, "icps", sa.Column("target_companies", sa.Text(), server_default="", nullable=False))
    _add_column_if_missing(inspector, "icps", sa.Column("keywords", sa.Text(), server_default="", nullable=False))
    _add_column_if_missing(inspector, "leads", sa.Column("linkedin_url", sa.String(255), server_default="", nullable=False))
    _add_column_if_missing(inspector, "leads", sa.Column("provider_ref", sa.String(200), server_default="", nullable=False))
    _add_column_if_missing(inspector, "leads", sa.Column("discovery_provider", sa.String(40), server_default="", nullable=False))
    _add_column_if_missing(inspector, "leads", sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "leads", sa.Column("discovery_confidence", sa.Integer(), server_default="0", nullable=False))
    _add_column_if_missing(inspector, "contacts", sa.Column("linkedin_url", sa.String(255), server_default="", nullable=False))
    _add_column_if_missing(inspector, "contacts", sa.Column("preferred_channel", sa.String(20), server_default="EMAIL", nullable=False))
    _add_column_if_missing(inspector, "contacts", sa.Column("consent_voice", sa.Boolean(), server_default=sa.false(), nullable=False))
    _add_column_if_missing(inspector, "campaigns", sa.Column("external_campaign_id", sa.String(200), server_default="", nullable=False))
    _add_column_if_missing(inspector, "campaigns", sa.Column("provider", sa.String(40), server_default="", nullable=False))
    _add_column_if_missing(inspector, "campaigns", sa.Column("provider_status", sa.String(20), server_default="", nullable=False))
    _add_column_if_missing(inspector, "campaigns", sa.Column("impressions", sa.Integer(), server_default="0", nullable=False))
    _add_column_if_missing(inspector, "campaigns", sa.Column("clicks", sa.Integer(), server_default="0", nullable=False))
    _add_column_if_missing(inspector, "campaigns", sa.Column("conversions", sa.Integer(), server_default="0", nullable=False))
    _add_column_if_missing(inspector, "campaigns", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "campaigns", sa.Column("launch_approval_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "conversations", sa.Column("call_status", sa.String(20), server_default="", nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("max_discovery_runs_per_day", sa.Integer(), server_default="4", nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("max_candidates_per_run", sa.Integer(), server_default="10", nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("max_candidates_per_day", sa.Integer(), server_default="25", nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("alert_rules_json", sa.Text(), server_default="{}", nullable=False))
    _add_column_if_missing(inspector, "provider_inbox_events", sa.Column("status", sa.String(20), server_default="received", nullable=False))
    _add_column_if_missing(inspector, "provider_inbox_events", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    return
