"""Social Growth Autopilot: brand facts, accounts, strategy, calendar, creative, publications, insights.

Revision ID: 046
Revises: 045

Downgrade is a no-op. Restoring the pre-046 backup returns the database to 045.
Every new tenant table gets FORCE ROW LEVEL SECURITY. Tracking links can also be
read by their public token hash so a redirect works without a session.
"""

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op
from app.db.base import Base
from app.models import *  # noqa: F403
from app.services.rbac import PERMISSIONS, ROLE_PERMISSIONS

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None

_TENANT_TABLES = (
    "growth_accounts",
    "brand_profiles",
    "brand_sources",
    "brand_facts",
    "competitor_benchmarks",
    "growth_business_events",
    "growth_strategies",
    "growth_calendar_items",
    "growth_creatives",
    "growth_assets",
    "growth_publications",
    "growth_media",
    "growth_metric_observations",
    "growth_link_clicks",
    "growth_traffic_observations",
    "growth_recommendations",
)
_TENANT_USING = "tenant_id::text = current_setting('app.current_tenant_id', true)"
_LINK_USING = (
    "tenant_id::text = current_setting('app.current_tenant_id', true) "
    "OR (current_setting('app.form_token_hash', true) <> '' "
    "AND token_hash = current_setting('app.form_token_hash', true))"
)
_FLAG = ("ENABLE_SOCIAL_GROWTH", "Social Growth Autopilot automation")


def _enable_rls(conn, table: str, using_sql: str) -> None:
    conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
    conn.execute(text(f'CREATE POLICY tenant_isolation ON "{table}" USING ({using_sql}) WITH CHECK ({using_sql})'))


def _add_column_if_missing(inspector, table: str, column: sa.Column) -> bool:
    if table not in inspector.get_table_names():
        return False
    existing = {col["name"] for col in inspector.get_columns(table)}
    if column.name in existing:
        return False
    op.add_column(table, column)
    return True


def _ensure_index(inspector, table: str, name: str, columns: list[str]) -> None:
    if table not in inspector.get_table_names():
        return
    if name in {index["name"] for index in inspector.get_indexes(table)}:
        return
    op.create_index(name, table, columns)


def _sync_permissions(bind) -> None:
    keys = [(key, description) for key, description in PERMISSIONS if key.startswith("social_growth.")]
    for key, description in keys:
        found = bind.execute(text("SELECT id FROM permissions WHERE key = :key"), {"key": key}).scalar()
        if found is None:
            bind.execute(
                text("INSERT INTO permissions (id, key, description) VALUES (:id, :key, :description)"),
                {"id": uuid4(), "key": key, "description": description},
            )
    permission_ids = {
        str(row.key): row.id
        for row in bind.execute(text("SELECT id, key FROM permissions WHERE key LIKE 'social_growth.%'"))
    }
    for role in bind.execute(text("SELECT id, name FROM roles")).all():
        wanted = [key for key in ROLE_PERMISSIONS.get(str(role.name), []) if key in permission_ids]
        for key in wanted:
            exists = bind.execute(
                text("SELECT 1 FROM role_permissions WHERE role_id = :role AND permission_id = :permission"),
                {"role": role.id, "permission": permission_ids[key]},
            ).scalar()
            if exists is None:
                bind.execute(
                    text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:role, :permission)"),
                    {"role": role.id, "permission": permission_ids[key]},
                )


def _seed_flag(bind) -> None:
    key, description = _FLAG
    for tenant_id in bind.execute(text("SELECT id FROM tenants")).scalars().all():
        exists = bind.execute(
            text("SELECT 1 FROM feature_flags WHERE tenant_id = :tenant AND key = :key"),
            {"tenant": tenant_id, "key": key},
        ).scalar()
        if exists is None:
            bind.execute(
                text(
                    "INSERT INTO feature_flags (id, tenant_id, key, enabled, description, created_at, updated_at) "
                    "VALUES (:id, :tenant, :key, :enabled, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": uuid4(), "tenant": tenant_id, "key": key, "enabled": False, "description": description},
            )


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    inspector = inspect(bind)
    for table in ("leads", "inbound_captures"):
        _add_column_if_missing(inspector, table, sa.Column("growth_link_id", sa.Uuid(), nullable=True))
    inspector = inspect(bind)
    _ensure_index(inspector, "leads", "ix_leads_growth_link_id", ["growth_link_id"])
    _ensure_index(inspector, "inbound_captures", "ix_inbound_captures_growth_link_id", ["growth_link_id"])
    _sync_permissions(bind)
    _seed_flag(bind)
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))
    names = set(inspect(bind).get_table_names())
    for table in _TENANT_TABLES:
        if table in names:
            _enable_rls(bind, table, _TENANT_USING)
    if "growth_tracking_links" in names:
        _enable_rls(bind, "growth_tracking_links", _LINK_USING)


def downgrade() -> None:
    return
