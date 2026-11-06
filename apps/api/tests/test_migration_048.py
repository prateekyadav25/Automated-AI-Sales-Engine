"""Upgrade 046 to 048 on a disposable database. The application database is not migrated.

The lead-intake exception stays on the lead-form tables. It does not open
growth accounts or the other tenant tables.
"""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from tests.test_migration_032 import _ADMIN, _APP, _alembic, _connect, _insert_required

TENANT_TABLES = (
    "content_proposals",
    "content_recommendations",
    "deal_purchases",
    "onboarding_completions",
    "organic_metric_observations",
    "paid_ads",
    "purchase_health_signals",
    "quote_acceptances",
    "lead_form_bindings",
    "lead_form_receipts",
    "growth_accounts",
    "growth_acceptance_gates",
)


def _security(conn, table: str) -> tuple[bool, bool]:
    row = conn.execute(
        text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :table"),
        {"table": table},
    ).one()
    return bool(row.relrowsecurity), bool(row.relforcerowsecurity)


def _policy(conn, table: str) -> str:
    return str(
        conn.execute(
            text(
                "SELECT pg_get_expr(polqual, polrelid) FROM pg_policy "
                "JOIN pg_class ON pg_class.oid = pg_policy.polrelid WHERE relname = :table"
            ),
            {"table": table},
        ).scalar()
        or ""
    )


@pytest.mark.postgres
def test_migration_048_keeps_the_application_database_and_isolates_acceptance() -> None:
    admin = _connect(_ADMIN)
    app_engine = None
    try:
        app_engine = create_engine(_APP)
        with app_engine.connect() as app_conn:
            assert app_conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "046"
    except SQLAlchemyError as exc:
        pytest.fail(f"The application database could not be read before the disposable upgrade ({type(exc).__name__})")
    finally:
        if app_engine is not None:
            app_engine.dispose()

    name = f"m048_{uuid4().hex[:12]}"
    url = _ADMIN.rsplit("/", 1)[0] + f"/{name}"
    disposable = None
    tenant_a, tenant_b = uuid4(), uuid4()
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        _alembic(url, "upgrade", "head")
        disposable = _connect(url)
        with disposable.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "048"
            for table in TENANT_TABLES:
                assert _security(conn, table) == (True, True), table
            assert "app.lead_intake" not in _policy(conn, "content_proposals")
            assert "app.lead_intake" not in _policy(conn, "growth_accounts")
            assert "app.lead_intake" not in _policy(conn, "growth_acceptance_gates")
            assert "app.lead_intake" in _policy(conn, "lead_form_receipts")
            _insert_required(conn, "tenants", {"id": tenant_a, "name": "Tenant A", "slug": f"a-{name}"})
            _insert_required(conn, "tenants", {"id": tenant_b, "name": "Tenant B", "slug": f"b-{name}"})
            _insert_required(conn, "growth_accounts", {"id": uuid4(), "tenant_id": tenant_a, "platform": "facebook", "external_id": "111"})
            _insert_required(conn, "growth_accounts", {"id": uuid4(), "tenant_id": tenant_b, "platform": "facebook", "external_id": "222"})
        rls = create_engine(url)
        try:
            with rls.connect() as conn:
                conn.execute(text("SET ROLE agrayian_app"))
                conn.execute(text("SELECT set_config('app.current_tenant_id', :tenant, true)"), {"tenant": str(tenant_a)})
                conn.execute(text("SELECT set_config('app.lead_intake', '1', true)"))
                visible = conn.execute(text("SELECT external_id FROM growth_accounts ORDER BY external_id")).scalars().all()
                assert visible == ["111"]
                with pytest.raises(DBAPIError, match="row-level security"):
                    conn.execute(
                        text(
                            "INSERT INTO growth_accounts (id, tenant_id, platform, external_id, page_id, name, username, provenance, status, "
                            "granted_scopes, missing_scopes, capabilities, last_error, timezone, posting_windows, daily_cap, api_version, created_at, updated_at) "
                            "VALUES (:id, :tenant, 'facebook', '333', '', '', '', 'live', 'unverified', '[]', '[]', '{}', '', 'UTC', '[]', 2, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ),
                        {"id": uuid4(), "tenant": tenant_b},
                    )
                conn.rollback()
        finally:
            rls.dispose()
        app_engine = create_engine(_APP)
        try:
            with app_engine.connect() as app_conn:
                assert app_conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "046"
        finally:
            app_engine.dispose()
    finally:
        if disposable is not None:
            disposable.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
