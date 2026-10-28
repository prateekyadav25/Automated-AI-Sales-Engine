"""Store a paused Meta campaign proposal and its ad.

Revision ID: 041
Revises: 040

Downgrade is a no-op. It does not drop the new columns or table.
"""

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op
from app.db.base import Base
from app.models import *  # noqa: F403

revision = "041"
down_revision = "040"
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
    columns = [
        sa.Column("operating_plan_id", sa.Uuid(), nullable=True),
        sa.Column("creative_version_id", sa.Uuid(), nullable=True),
        sa.Column("audience", sa.Text(), nullable=False, server_default=""),
        sa.Column("geography", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("placements", sa.Text(), nullable=False, server_default=""),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("headline", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("call_to_action", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("asset_ref", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("destination", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("assembly_status", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("assembly_blocker", sa.Text(), nullable=False, server_default=""),
        sa.Column("context_json", sa.Text(), nullable=False, server_default=""),
    ]
    for column in columns:
        _add_column_if_missing(inspector, "campaigns", column)
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))


def downgrade() -> None:
    return
