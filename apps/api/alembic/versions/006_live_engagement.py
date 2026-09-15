"""Live engagement tables and outreach columns.

Revision ID: 006
Revises: 005
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "006"
down_revision = "005"
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
    _add_column_if_missing(inspector, "conversations", sa.Column("provider_thread_id", sa.String(200), server_default="", nullable=False))
    _add_column_if_missing(inspector, "conversations", sa.Column("lead_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "meeting_records", sa.Column("lead_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "meeting_records", sa.Column("contact_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "meeting_records", sa.Column("owner_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "meeting_records", sa.Column("start_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "meeting_records", sa.Column("end_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "meeting_records", sa.Column("timezone", sa.String(64), server_default="UTC", nullable=False))
    _add_column_if_missing(inspector, "meeting_records", sa.Column("status", sa.String(40), server_default="logged", nullable=False))
    _add_column_if_missing(inspector, "meeting_records", sa.Column("provider_event_id", sa.String(200), nullable=True))
    _add_column_if_missing(inspector, "meeting_records", sa.Column("calendar_account", sa.String(255), server_default="", nullable=False))
    _add_column_if_missing(inspector, "autopilot_settings", sa.Column("max_emails_per_day", sa.Integer(), server_default="50", nullable=False))
    _add_column_if_missing(
        inspector,
        "autopilot_settings",
        sa.Column("max_emails_per_contact_per_day", sa.Integer(), server_default="2", nullable=False),
    )
    _add_column_if_missing(
        inspector,
        "autopilot_settings",
        sa.Column("minimum_hours_between_outreach", sa.Integer(), server_default="24", nullable=False),
    )


def downgrade() -> None:
    return
