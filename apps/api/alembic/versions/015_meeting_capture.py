"""Meeting capture records and consent evidence.

Revision ID: 015
Revises: 014
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "015"
down_revision = "014"
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
        ("meeting_records", sa.Column("recording_consent", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("meeting_records", sa.Column("insights_json", sa.Text(), server_default="{}", nullable=False)),
        ("meeting_records", sa.Column("transcript", sa.Text(), server_default="", nullable=False)),
    ]:
        _add_column_if_missing(inspector, table, column)
    if bind.dialect.name != "postgresql":
        return
    conn = bind
    conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))
    if "meeting_captures" in inspect(bind).get_table_names():
        _enable_rls(conn, "meeting_captures", "tenant_id::text = current_setting('app.current_tenant_id', true)")


def downgrade() -> None:
    return
