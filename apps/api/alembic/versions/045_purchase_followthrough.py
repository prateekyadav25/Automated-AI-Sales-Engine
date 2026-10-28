"""Bind onboarding, health signals, and completion history to a purchase.

Revision ID: 045
Revises: 044

Downgrade is a no-op. Restoring the pre-045 backup returns the database to 044.
"""

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op
from app.db.base import Base
from app.models import *  # noqa: F403

revision = "045"
down_revision = "044"
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
    plan_columns = [
        sa.Column("purchase_id", sa.Uuid(), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_evidence", sa.Text(), nullable=False, server_default=""),
    ]
    item_columns = [
        sa.Column("purchase_id", sa.Uuid(), nullable=True),
        sa.Column("step", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("review_state", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("waiver_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("provenance", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
    ]
    for column in plan_columns:
        _add_column_if_missing(inspector, "onboarding_plans", column)
    for column in item_columns:
        _add_column_if_missing(inspector, "onboarding_milestones", column)
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))


def downgrade() -> None:
    return
