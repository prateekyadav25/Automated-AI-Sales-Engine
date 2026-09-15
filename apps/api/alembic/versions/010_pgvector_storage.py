"""pgvector column, object metadata, uniques, emergency flags.

Revision ID: 010
Revises: 009
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.db.base import Base
from app.models import *  # noqa: F403

revision = "010"
down_revision = "009"
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
    for table, column in [
        ("knowledge_sources", sa.Column("object_key", sa.String(400), server_default="", nullable=False)),
        ("knowledge_sources", sa.Column("original_filename", sa.String(255), server_default="", nullable=False)),
        ("knowledge_sources", sa.Column("byte_size", sa.Integer(), server_default="0", nullable=False)),
        ("knowledge_sources", sa.Column("checksum", sa.String(64), server_default="", nullable=False)),
        ("knowledge_sources", sa.Column("malware_status", sa.String(40), server_default="NOT_CONFIGURED", nullable=False)),
        ("ai_approvals", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)),
        ("autopilot_settings", sa.Column("emergency_stop", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("autopilot_settings", sa.Column("email_channel_paused", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("autopilot_settings", sa.Column("ads_channel_paused", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("autopilot_settings", sa.Column("voice_channel_paused", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("autopilot_settings", sa.Column("discovery_channel_paused", sa.Boolean(), server_default=sa.false(), nullable=False)),
    ]:
        _add_column_if_missing(inspector, table, column)

    if bind.dialect.name != "postgresql":
        return

    dims = get_settings().embedding_dimensions
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    bind.execute(text(f"ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding vector({int(dims)})"))
    # No IVFFlat/HNSW yet. Add vector_cosine_ops when chunk counts leave the small-tenant range.
    bind.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_opportunity
            ON customers (tenant_id, opportunity_id)
            WHERE opportunity_id IS NOT NULL AND deleted_at IS NULL
            """
        )
    )
    bind.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_renewals_customer
            ON renewals (tenant_id, customer_id)
            WHERE deleted_at IS NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("DROP INDEX IF EXISTS uq_customers_opportunity"))
    bind.execute(text("DROP INDEX IF EXISTS uq_renewals_customer"))
    bind.execute(text("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding"))
