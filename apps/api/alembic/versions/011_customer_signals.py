"""Customer signals, identity mapping, and rules-v2 columns.

Revision ID: 011
Revises: 010
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "011"
down_revision = "010"
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
        ("provider_accounts", sa.Column("account_key", sa.String(120), server_default="default", nullable=False)),
        ("autopilot_settings", sa.Column("usage_freshness_hours", sa.Integer(), server_default="72", nullable=False)),
        ("autopilot_settings", sa.Column("support_freshness_hours", sa.Integer(), server_default="168", nullable=False)),
        ("autopilot_settings", sa.Column("finance_freshness_hours", sa.Integer(), server_default="168", nullable=False)),
        ("autopilot_settings", sa.Column("high_utilization_pct", sa.Integer(), server_default="85", nullable=False)),
        ("autopilot_settings", sa.Column("low_utilization_pct", sa.Integer(), server_default="30", nullable=False)),
        ("autopilot_settings", sa.Column("usage_live_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("autopilot_settings", sa.Column("support_live_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("autopilot_settings", sa.Column("finance_live_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("autopilot_settings", sa.Column("erp_live_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("autopilot_settings", sa.Column("raw_payload_retention_days", sa.Integer(), server_default="30", nullable=False)),
        ("autopilot_settings", sa.Column("minimum_health_coverage", sa.Integer(), server_default="40", nullable=False)),
        ("health_scores", sa.Column("health_data_coverage", sa.Integer(), server_default="0", nullable=False)),
        ("health_score_snapshots", sa.Column("health_data_coverage", sa.Integer(), server_default="0", nullable=False)),
        ("renewals", sa.Column("why_ready_json", sa.Text(), server_default="[]", nullable=False)),
        ("renewals", sa.Column("why_at_risk_json", sa.Text(), server_default="[]", nullable=False)),
    ]:
        _add_column_if_missing(inspector, table, column)

    if bind.dialect.name != "postgresql":
        return

    conn = bind
    conn.execute(
        text(
            """
            UPDATE provider_accounts
            SET account_key = COALESCE(NULLIF(account_key, ''), connected_user_id::text, 'default')
            WHERE account_key = 'default' AND connected_user_id IS NOT NULL
            """
        )
    )
    conn.execute(text("ALTER TABLE provider_accounts ALTER COLUMN connected_user_id DROP NOT NULL"))
    conn.execute(
        text(
            """
            DO $$
            DECLARE rec record;
            BEGIN
              FOR rec IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'provider_accounts'::regclass AND contype = 'u'
                  AND conname <> 'uq_provider_account_key'
              LOOP
                EXECUTE format('ALTER TABLE provider_accounts DROP CONSTRAINT IF EXISTS %I', rec.conname);
              END LOOP;
            END$$;
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_account_key
            ON provider_accounts (tenant_id, provider, account_key)
            """
        )
    )
    conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))
    conn.execute(
        text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agrayian_app")
    )
    tables = [
        row[0]
        for row in conn.execute(
            text(
                """
                SELECT table_name FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name = 'tenant_id'
                ORDER BY table_name
                """
            )
        )
    ]
    for table in tables:
        if table == "users":
            using = (
                "tenant_id::text = current_setting('app.current_tenant_id', true) "
                "OR (current_setting('app.login_email', true) <> '' AND email = current_setting('app.login_email', true))"
            )
        elif table == "refresh_tokens":
            using = (
                "tenant_id::text = current_setting('app.current_tenant_id', true) "
                "OR (current_setting('app.refresh_token_hash', true) <> '' AND token_hash = current_setting('app.refresh_token_hash', true))"
            )
        elif table == "webhook_routes":
            using = (
                "tenant_id::text = current_setting('app.current_tenant_id', true) "
                "OR (current_setting('app.webhook_token_hash', true) <> '' AND token_hash = current_setting('app.webhook_token_hash', true))"
            )
        else:
            using = "tenant_id::text = current_setting('app.current_tenant_id', true)"
        _enable_rls(conn, table, using)
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_signal_ref_present
            ON customer_signals (tenant_id, source_provider, external_reference)
            WHERE external_reference IS NOT NULL AND deleted_at IS NULL
            """
        )
    )


def downgrade() -> None:
    return
