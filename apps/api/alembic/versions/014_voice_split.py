"""Voice telephony/conversation split, scripts, sessions, and tenant credential config.

Revision ID: 014
Revises: 013
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "014"
down_revision = "013"
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
        ("provider_accounts", sa.Column("config_encrypted", sa.Text(), server_default="", nullable=False)),
        ("contacts", sa.Column("consent_recording", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("contacts", sa.Column("ndnc_status", sa.String(20), server_default="", nullable=False)),
        ("autopilot_settings", sa.Column("voice_telephony_override", sa.String(40), server_default="", nullable=False)),
        ("autopilot_settings", sa.Column("voice_conversation_provider", sa.String(40), server_default="vapi", nullable=False)),
    ]:
        _add_column_if_missing(inspector, table, column)
    if bind.dialect.name != "postgresql":
        return
    conn = bind
    conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))
    for table in ("voice_scripts", "voice_script_versions", "voice_sessions"):
        if table in inspect(bind).get_table_names():
            _enable_rls(conn, table, "tenant_id::text = current_setting('app.current_tenant_id', true)")


def downgrade() -> None:
    return
