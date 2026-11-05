"""Upgrade 045 to 046 on a disposable database. The application database is not migrated.

Downgrade is a no-op. Recovery is restoring the backup taken before upgrade and
restarting the API and workers. This test drops only the database it creates.
"""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.services.public_forms import hash_form_token
from tests.test_migration_032 import _ADMIN, _APP, _alembic, _connect, _insert_required

GROWTH_TABLES = (
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
    "growth_tracking_links",
)


def _security(conn, table: str) -> tuple[bool, bool]:
    row = conn.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :table"), {"table": table}).one()
    return bool(row.relrowsecurity), bool(row.relforcerowsecurity)


@pytest.mark.postgres
def test_migration_046_adds_growth_tables_with_forced_tenant_isolation() -> None:
    admin = _connect(_ADMIN)
    app_version = None
    app_engine = None
    try:
        app_engine = create_engine(_APP)
        with app_engine.connect() as app_conn:
            app_version = app_conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError:
        app_version = None
    finally:
        if app_engine is not None:
            app_engine.dispose()

    name = f"m046_{uuid4().hex[:12]}"
    url = _ADMIN.rsplit("/", 1)[0] + f"/{name}"
    disposable = None
    tenant_a, tenant_b = uuid4(), uuid4()
    raw_token = "fixture-link-token-046"
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        _alembic(url, "upgrade", "045")
        disposable = _connect(url)
        with disposable.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "045"
            _insert_required(conn, "tenants", {"id": tenant_a, "name": "Tenant A", "slug": f"a-{name}"})
            _insert_required(conn, "tenants", {"id": tenant_b, "name": "Tenant B", "slug": f"b-{name}"})
            _insert_required(conn, "roles", {"id": uuid4(), "tenant_id": tenant_a, "name": "Tenant Admin"})
            _insert_required(conn, "roles", {"id": uuid4(), "tenant_id": tenant_b, "name": "Read Only"})
        _alembic(url, "upgrade", "046")
        with disposable.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "046"
            present = set(conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars().all())
            assert set(GROWTH_TABLES) <= present
            for table in GROWTH_TABLES:
                assert _security(conn, table) == (True, True), table
            grants = set(
                conn.execute(
                    text("SELECT privilege_type FROM information_schema.role_table_grants WHERE grantee = 'agrayian_app' AND table_name = 'growth_publications'")
                ).scalars().all()
            )
            assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= grants
            for table in ("leads", "inbound_captures"):
                column = conn.execute(
                    text("SELECT data_type FROM information_schema.columns WHERE table_name = :table AND column_name = 'growth_link_id'"),
                    {"table": table},
                ).scalar()
                assert column == "uuid"
            role_keys = {
                (str(row.name), str(row.key))
                for row in conn.execute(
                    text(
                        "SELECT r.name, p.key FROM roles r JOIN role_permissions rp ON rp.role_id = r.id "
                        "JOIN permissions p ON p.id = rp.permission_id WHERE p.key LIKE 'social_growth.%'"
                    )
                )
            }
            assert {("Tenant Admin", "social_growth.read"), ("Tenant Admin", "social_growth.write"), ("Tenant Admin", "social_growth.approve")} <= role_keys
            assert ("Read Only", "social_growth.read") in role_keys and ("Read Only", "social_growth.write") not in role_keys
            flags = conn.execute(text("SELECT tenant_id, enabled FROM feature_flags WHERE key = 'ENABLE_SOCIAL_GROWTH'")).all()
            assert {row.tenant_id for row in flags} == {tenant_a, tenant_b} and not any(row.enabled for row in flags)
            for tenant, label in ((tenant_a, "Visible page"), (tenant_b, "Hidden page")):
                _insert_required(conn, "growth_accounts", {"id": uuid4(), "tenant_id": tenant, "platform": "facebook", "external_id": str(uuid4().int)[:12], "name": label})
            _insert_required(
                conn,
                "growth_tracking_links",
                {"id": uuid4(), "tenant_id": tenant_b, "token": raw_token, "token_hash": hash_form_token(raw_token), "destination_url": "https://example.test/form"},
            )
        rls = create_engine(url)
        try:
            with rls.connect() as conn:
                conn.execute(text("SET ROLE agrayian_app"))
                conn.execute(text("SELECT set_config('app.current_tenant_id', :tenant, true)"), {"tenant": str(tenant_a)})
                assert conn.execute(text("SELECT name FROM growth_accounts")).scalars().all() == ["Visible page"]
                assert conn.execute(text("SELECT count(*) FROM growth_tracking_links")).scalar() == 0
                conn.rollback()
            with rls.connect() as conn:
                conn.execute(text("SET ROLE agrayian_app"))
                conn.execute(text("SELECT set_config('app.current_tenant_id', '', true)"))
                conn.execute(text("SELECT set_config('app.form_token_hash', :hash, true)"), {"hash": hash_form_token(raw_token)})
                assert conn.execute(text("SELECT destination_url FROM growth_tracking_links")).scalars().all() == ["https://example.test/form"]
                assert conn.execute(text("SELECT count(*) FROM growth_accounts")).scalar() == 0
                conn.rollback()
        finally:
            rls.dispose()
        _alembic(url, "downgrade", "-1")
        with disposable.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "045"
            assert conn.execute(text("SELECT count(*) FROM growth_accounts")).scalar() == 2
    finally:
        if disposable is not None:
            disposable.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
        if app_version is not None:
            check = create_engine(_APP)
            try:
                with check.connect() as conn:
                    after = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                assert after == app_version
            finally:
                check.dispose()
