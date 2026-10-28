"""Store a permissioned callback on the existing voice session.

Revision ID: 043
Revises: 042

Downgrade is a no-op. It does not drop the new columns.
"""

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op
from app.db.base import Base
from app.models import *  # noqa: F403

revision = "043"
down_revision = "042"
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
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("capture_id", sa.Uuid(), nullable=True),
        sa.Column("operating_plan_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=""),
        sa.Column("caller_identity", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("recipient_e164", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocker", sa.Text(), nullable=False, server_default=""),
        sa.Column("operation_token", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("call_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recording_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("events_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="-1"),
        sa.Column("handoff_task_id", sa.Uuid(), nullable=True),
        sa.Column("meeting_id", sa.Uuid(), nullable=True),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=True),
        sa.Column("context_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("fixture", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_event", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    ]
    for column in columns:
        _add_column_if_missing(inspector, "voice_sessions", column)
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))


def downgrade() -> None:
    return
