"""RLS, refresh-token family, webhook routes, tenant_id on child tables.

Revision ID: 009
Revises: 008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.db.base import Base
from app.models import *  # noqa: F403

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None

JOIN_POLICIES = {
    "user_roles": "EXISTS (SELECT 1 FROM users u WHERE u.id = user_roles.user_id AND u.tenant_id::text = current_setting('app.current_tenant_id', true))",
    "team_members": "EXISTS (SELECT 1 FROM teams t WHERE t.id = team_members.team_id AND t.tenant_id::text = current_setting('app.current_tenant_id', true))",
}


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
    _add_column_if_missing(inspector, "refresh_tokens", sa.Column("token_family_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "refresh_tokens", sa.Column("jti_hash", sa.String(64), server_default="", nullable=False))
    _add_column_if_missing(inspector, "refresh_tokens", sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "refresh_tokens", sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "refresh_tokens", sa.Column("replaced_by", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "refresh_tokens", sa.Column("reuse_detected_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(inspector, "tool_calls", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "ai_messages", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    _add_column_if_missing(inspector, "domain_events", sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False))

    if bind.dialect.name != "postgresql":
        return

    conn = bind
    conn.execute(text("UPDATE refresh_tokens SET token_family_id = id WHERE token_family_id IS NULL"))
    conn.execute(text("UPDATE refresh_tokens SET issued_at = created_at WHERE issued_at IS NULL"))
    conn.execute(
        text(
            """
            UPDATE tool_calls tc
            SET tenant_id = ar.tenant_id
            FROM agent_runs ar
            WHERE tc.run_id = ar.id AND tc.tenant_id IS NULL
            """
        )
    )
    conn.execute(
        text(
            """
            UPDATE ai_messages m
            SET tenant_id = c.tenant_id
            FROM ai_conversations c
            WHERE m.conversation_id = c.id AND m.tenant_id IS NULL
            """
        )
    )
    password = get_settings().app_db_password.replace("'", "''")
    conn.execute(
        text(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agrayian_app') THEN
                CREATE ROLE agrayian_app LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agrayian_migrator') THEN
                CREATE ROLE agrayian_migrator NOLOGIN BYPASSRLS;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agrayian_admin') THEN
                CREATE ROLE agrayian_admin NOLOGIN BYPASSRLS;
              END IF;
            END$$;
            """
        )
    )
    conn.execute(
        text(
            """
            DO $$
            BEGIN
              EXECUTE format('GRANT CONNECT ON DATABASE %I TO agrayian_app, agrayian_migrator, agrayian_admin', current_database());
            END$$;
            """
        )
    )
    conn.execute(text("GRANT USAGE ON SCHEMA public TO agrayian_app, agrayian_migrator, agrayian_admin"))
    conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))
    conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_migrator, agrayian_admin"))
    conn.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO agrayian_app, agrayian_migrator, agrayian_admin"))
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

    for table, using in JOIN_POLICIES.items():
        exists = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t"),
            {"t": table},
        ).first()
        if exists:
            _enable_rls(conn, table, using)

    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_approval_idempotency
            ON ai_approvals (tenant_id, idempotency_key)
            WHERE idempotency_key <> ''
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    tables = [
        row[0]
        for row in bind.execute(
            text(
                """
                SELECT table_name FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name = 'tenant_id'
                """
            )
        )
    ]
    for table in tables + list(JOIN_POLICIES):
        bind.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
        bind.execute(text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
        bind.execute(text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
