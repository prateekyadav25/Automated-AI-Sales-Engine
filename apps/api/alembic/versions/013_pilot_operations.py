"""Controlled production pilot foundation.

Revision ID: 013
Revises: 012
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "013"
down_revision = "012"
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
        ("tenants", sa.Column("operating_mode", sa.String(20), server_default="DEMO", nullable=False)),
        ("autopilot_settings", sa.Column("ai_daily_budget", sa.Numeric(18, 4), server_default="0", nullable=False)),
        ("autopilot_settings", sa.Column("max_calls_per_day", sa.Integer(), server_default="10", nullable=False)),
        (
            "autopilot_settings",
            sa.Column("allow_deployment_provider_defaults", sa.Boolean(), server_default=sa.true(), nullable=False),
        ),
        ("autopilot_settings", sa.Column("allow_unscanned_uploads", sa.Boolean(), server_default=sa.true(), nullable=False)),
        ("autopilot_settings", sa.Column("whatsapp_channel_paused", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("autopilot_settings", sa.Column("current_policy_version", sa.Integer(), server_default="1", nullable=False)),
        ("contacts", sa.Column("consent_whatsapp", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("leads", sa.Column("consent_whatsapp", sa.Boolean(), server_default=sa.false(), nullable=False)),
        ("customers", sa.Column("churn_reason", sa.String(80), server_default="", nullable=False)),
        ("expansion_recommendations", sa.Column("outcome_status", sa.String(40), server_default="", nullable=False)),
        ("expansion_recommendations", sa.Column("outcome_value", sa.Numeric(18, 2), nullable=True)),
        ("expansion_recommendations", sa.Column("outcome_product", sa.String(120), server_default="", nullable=False)),
        ("knowledge_sources", sa.Column("quarantine_key", sa.String(400), server_default="", nullable=False)),
        ("provider_actions", sa.Column("provider_mode", sa.String(20), server_default="", nullable=False)),
        ("provider_actions", sa.Column("provider_account_id", sa.Uuid(), nullable=True)),
        ("provider_actions", sa.Column("policy_version", sa.Integer(), server_default="0", nullable=False)),
        ("recommendation_feedback", sa.Column("useful", sa.String(8), server_default="", nullable=False)),
        ("ml_feature_snapshots", sa.Column("correction_of_id", sa.Uuid(), nullable=True)),
    ]:
        _add_column_if_missing(inspector, table, column)

    if bind.dialect.name != "postgresql":
        return

    conn = bind
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


def downgrade() -> None:
    return
