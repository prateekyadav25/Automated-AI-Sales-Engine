"""Store a Google Meet booking on the existing meeting record.

Revision ID: 042
Revises: 041

Downgrade is a no-op. It does not drop the new columns.
"""

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op
from app.db.base import Base
from app.models import *  # noqa: F403

revision = "042"
down_revision = "041"
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
        sa.Column("capture_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=""),
        sa.Column("calendar_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("client_event_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("conference_request_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("conference_id", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("join_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("conference_status", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("blocker", sa.Text(), nullable=False, server_default=""),
        sa.Column("context_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("attendees_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("slots_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("selected_slot_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("owner_timezone", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("attendee_timezone", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("availability_retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("booking_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("operation_token", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("booking_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("invite_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=True),
    ]
    for column in columns:
        _add_column_if_missing(inspector, "meeting_records", column)
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))


def downgrade() -> None:
    return
