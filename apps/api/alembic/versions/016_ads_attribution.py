"""Ad sets, creatives, audiences, daily metrics, and attribution columns.

Revision ID: 016
Revises: 015
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def _add_column_if_missing(inspector, table: str, column: sa.Column) -> None:
    if table not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table)}
    if column.name in existing:
        return
    op.add_column(table, column)


def _enable_rls(conn, table: str, using_sql: str) -> None:
    conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
    conn.execute(text(f'CREATE POLICY tenant_isolation ON "{table}" USING ({using_sql}) WITH CHECK ({using_sql})'))


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    inspector = inspect(bind)
    for table, column in [
        ("campaigns", sa.Column("ctr", sa.Numeric(18, 6), nullable=True)),
        ("campaigns", sa.Column("cpc", sa.Numeric(18, 4), nullable=True)),
        ("campaigns", sa.Column("cpl", sa.Numeric(18, 4), nullable=True)),
        ("ad_creatives", sa.Column("last_error", sa.Text(), server_default="", nullable=False)),
        ("leads", sa.Column("campaign_id", sa.Uuid(), nullable=True)),
        ("leads", sa.Column("ad_id", sa.String(120), server_default="", nullable=False)),
        ("leads", sa.Column("utm_medium", sa.String(80), server_default="", nullable=False)),
        ("leads", sa.Column("utm_campaign", sa.String(120), server_default="", nullable=False)),
        ("opportunities", sa.Column("campaign_id", sa.Uuid(), nullable=True)),
        ("opportunities", sa.Column("ad_id", sa.String(120), server_default="", nullable=False)),
        ("opportunities", sa.Column("utm_source", sa.String(80), server_default="", nullable=False)),
        ("opportunities", sa.Column("utm_medium", sa.String(80), server_default="", nullable=False)),
        ("opportunities", sa.Column("utm_campaign", sa.String(120), server_default="", nullable=False)),
        ("inbound_captures", sa.Column("campaign_id", sa.Uuid(), nullable=True)),
        ("inbound_captures", sa.Column("ad_id", sa.String(120), server_default="", nullable=False)),
    ]:
        _add_column_if_missing(inspector, table, column)
    if bind.dialect.name != "postgresql":
        return
    conn = bind
    conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))
    for table in ("ad_sets", "ad_creatives", "ad_audiences", "campaign_metric_daily", "public_form_keys"):
        if table in inspect(bind).get_table_names():
            _enable_rls(conn, table, "tenant_id::text = current_setting('app.current_tenant_id', true)")


def downgrade() -> None:
    return
