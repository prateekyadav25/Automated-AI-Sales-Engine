"""Store a quoted commercial snapshot, acceptance, and close-won purchase.

Revision ID: 044
Revises: 043

Downgrade is a no-op. It does not drop the new columns or tables.
"""

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op
from app.db.base import Base
from app.models import *  # noqa: F403

revision = "044"
down_revision = "043"
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
    quote_columns = [
        sa.Column("currency", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("customer_facing_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("offer_label", sa.Text(), nullable=False, server_default=""),
        sa.Column("sku", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("scope_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("billing_cadence", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("service_start", sa.Date(), nullable=True),
        sa.Column("service_end", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operating_plan_id", sa.Uuid(), nullable=True),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("parent_quote_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column("context_version", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("context_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("fixture", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]
    line_columns = [
        sa.Column("customer_facing_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("offer_label", sa.Text(), nullable=False, server_default=""),
        sa.Column("sku", sa.String(length=40), nullable=False, server_default=""),
    ]
    plan_columns = [
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("quote_id", sa.Uuid(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("blocker", sa.Text(), nullable=False, server_default=""),
    ]
    for column in quote_columns:
        _add_column_if_missing(inspector, "quotes", column)
    for column in line_columns:
        _add_column_if_missing(inspector, "quote_lines", column)
    for column in plan_columns:
        _add_column_if_missing(inspector, "onboarding_plans", column)
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))


def downgrade() -> None:
    return
