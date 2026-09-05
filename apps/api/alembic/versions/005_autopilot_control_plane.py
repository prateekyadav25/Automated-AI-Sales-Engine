"""Autopilot control plane tables and resume columns.

Revision ID: 005
Revises: 004
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "005"
down_revision = "004"
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
    _add_column_if_missing(inspector, "autonomous_runs", sa.Column("workflow", sa.String(80), server_default="cycle", nullable=False))
    _add_column_if_missing(inspector, "autonomous_runs", sa.Column("trigger_event", sa.String(80), server_default="", nullable=False))
    _add_column_if_missing(inspector, "autonomous_run_steps", sa.Column("entity_type", sa.String(40), server_default="", nullable=False))
    _add_column_if_missing(inspector, "autonomous_run_steps", sa.Column("entity_id", sa.String(64), server_default="", nullable=False))
    _add_column_if_missing(inspector, "autonomous_run_steps", sa.Column("attempt", sa.Integer(), server_default="1", nullable=False))
    _add_column_if_missing(inspector, "autonomous_run_steps", sa.Column("error", sa.Text(), server_default="", nullable=False))
    _add_column_if_missing(inspector, "autonomous_run_steps", sa.Column("idempotency_key", sa.String(200), server_default="", nullable=False))
    _add_column_if_missing(inspector, "ai_approvals", sa.Column("run_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "ai_approvals", sa.Column("entity_type", sa.String(40), server_default="", nullable=False))
    _add_column_if_missing(inspector, "ai_approvals", sa.Column("entity_id", sa.String(64), server_default="", nullable=False))
    _add_column_if_missing(inspector, "ai_approvals", sa.Column("idempotency_key", sa.String(200), server_default="", nullable=False))


def downgrade() -> None:
    return
