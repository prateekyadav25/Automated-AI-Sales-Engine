"""Revenue intelligence data foundation.

Revision ID: 012
Revises: 011
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "012"
down_revision = "011"
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
        ("ml_feature_snapshots", sa.Column("task_key", sa.String(60), server_default="", nullable=False)),
        ("ml_feature_snapshots", sa.Column("feature_set_version", sa.String(40), server_default="v1", nullable=False)),
        ("ml_feature_snapshots", sa.Column("as_of", sa.DateTime(timezone=True), nullable=True)),
        ("ml_feature_snapshots", sa.Column("source_versions_json", sa.Text(), server_default="{}", nullable=False)),
        ("ml_feature_snapshots", sa.Column("immutable", sa.Boolean(), server_default=sa.true(), nullable=False)),
        ("ml_outcome_labels", sa.Column("task_key", sa.String(60), server_default="", nullable=False)),
        ("ml_outcome_labels", sa.Column("label_version", sa.String(20), server_default="v1", nullable=False)),
        ("ml_outcome_labels", sa.Column("label_status", sa.String(20), server_default="PENDING", nullable=False)),
        ("ml_outcome_labels", sa.Column("horizon_days", sa.Integer(), server_default="90", nullable=False)),
        ("ml_outcome_labels", sa.Column("label_observed_at", sa.DateTime(timezone=True), nullable=True)),
        ("ml_outcome_labels", sa.Column("feature_snapshot_id", sa.Uuid(), nullable=True)),
        ("model_cards", sa.Column("last_trained", sa.DateTime(timezone=True), nullable=True)),
        ("model_cards", sa.Column("task_key", sa.String(60), server_default="", nullable=False)),
        ("model_cards", sa.Column("algorithm", sa.String(80), server_default="rules", nullable=False)),
        ("model_cards", sa.Column("dataset_version", sa.String(40), server_default="", nullable=False)),
        ("model_cards", sa.Column("metrics_json", sa.Text(), nullable=True)),
        ("model_cards", sa.Column("limitations", sa.Text(), server_default="", nullable=False)),
        ("forecast_snapshots", sa.Column("payload_json", sa.Text(), server_default="{}", nullable=False)),
    ]:
        _add_column_if_missing(inspector, table, column)

    if bind.dialect.name != "postgresql":
        return

    conn = bind
    conn.execute(text("ALTER TABLE ml_outcome_labels DROP CONSTRAINT IF EXISTS uq_ml_outcome"))
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_ml_outcome_task
            ON ml_outcome_labels (tenant_id, entity_type, entity_id, task_key, label_version)
            WHERE deleted_at IS NULL
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_ml_feature_as_of
            ON ml_feature_snapshots (tenant_id, entity_type, entity_id, task_key, feature_set_version, as_of)
            WHERE deleted_at IS NULL
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


def downgrade() -> None:
    return
