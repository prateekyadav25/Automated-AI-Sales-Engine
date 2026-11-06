"""Upgrade 046 to 047 on a disposable database. The application database is not migrated.

Downgrade is a no-op. Recovery is restoring the backup taken before upgrade.
This test drops only the database it creates.
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
)
GROWTH_TABLES = ("growth_accounts", "growth_publications", "growth_tracking_links")


def _security(conn, table: str) -> tuple[bool, bool]:
    row = conn.execute(
        text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :table"),
        {"table": table},
    ).one()
    return bool(row.relrowsecurity), bool(row.relforcerowsecurity)


@pytest.mark.postgres
def test_migration_047_isolates_the_backfilled_tables_and_keeps_growth_forced() -> None:
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

    name = f"m047_{uuid4().hex[:12]}"
    url = _ADMIN.rsplit("/", 1)[0] + f"/{name}"
    disposable = None
    tenant_a, tenant_b = uuid4(), uuid4()
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        _alembic(url, "upgrade", "046")
        disposable = _connect(url)
        with disposable.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "046"
            _insert_required(conn, "tenants", {"id": tenant_a, "name": "Tenant A", "slug": f"a-{name}"})
            _insert_required(conn, "tenants", {"id": tenant_b, "name": "Tenant B", "slug": f"b-{name}"})
        _alembic(url, "upgrade", "047")
        with disposable.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "047"
            for table in (*TENANT_TABLES, *GROWTH_TABLES):
                assert _security(conn, table) == (True, True), table
            link_policy = conn.execute(
                text(
                    "SELECT pg_get_expr(polqual, polrelid) FROM pg_policy "
                    "JOIN pg_class ON pg_class.oid = pg_policy.polrelid WHERE relname = 'growth_tracking_links'"
                )
            ).scalar()
            assert "app.form_token_hash" in str(link_policy)
            for tenant_id, lead_id in ((tenant_a, "lead-visible"), (tenant_b, "lead-hidden"), (None, "lead-unbound")):
                _insert_required(
                    conn,
                    "lead_form_receipts",
                    {"id": uuid4(), "tenant_id": tenant_id, "provider": "meta", "provider_lead_id": lead_id, "status": "received"},
                )
        rls = create_engine(url)
        try:
            with rls.connect() as conn:
                conn.execute(text("SET ROLE agrayian_app"))
                conn.execute(text("SELECT set_config('app.current_tenant_id', :tenant, true)"), {"tenant": str(tenant_a)})
                conn.execute(text("SELECT set_config('app.lead_intake', '', true)"))
                assert conn.execute(text("SELECT provider_lead_id FROM lead_form_receipts ORDER BY provider_lead_id")).scalars().all() == ["lead-visible"]
                with pytest.raises(DBAPIError):
                    conn.execute(
                        text(
                            "INSERT INTO lead_form_receipts (id, tenant_id, provider, provider_lead_id, page_id, form_id, ad_id, adgroup_id, "
                            "provider_campaign_id, attribution, notification_json, detail_json, permission_json, answers_json, status, error, attempts, created_at, updated_at) "
                            "VALUES (:id, :tenant, 'meta', 'lead-smuggled', '', '', '', '', '', '', '', '', '', '', 'received', '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ),
                        {"id": uuid4(), "tenant": tenant_b},
                    )
                conn.rollback()
            with rls.connect() as conn:
                conn.execute(text("SET ROLE agrayian_app"))
                conn.execute(text("SELECT set_config('app.current_tenant_id', '', true)"))
                conn.execute(text("SELECT set_config('app.lead_intake', '1', true)"))
                found = set(conn.execute(text("SELECT provider_lead_id FROM lead_form_receipts")).scalars().all())
                assert found == {"lead-visible", "lead-hidden", "lead-unbound"}
                conn.execute(
                    text(
                        "INSERT INTO lead_form_receipts (id, tenant_id, provider, provider_lead_id, page_id, form_id, ad_id, adgroup_id, "
                        "provider_campaign_id, attribution, notification_json, detail_json, permission_json, answers_json, status, error, attempts, created_at, updated_at) "
                        "VALUES (:id, NULL, 'meta', 'lead-from-webhook', '', '', '', '', '', '', '', '', '', '', 'received', '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"id": uuid4()},
                )
                assert conn.execute(text("SELECT count(*) FROM lead_form_receipts WHERE provider_lead_id = 'lead-from-webhook'")).scalar() == 1
                conn.rollback()
            with rls.connect() as conn:
                conn.execute(text("SET ROLE agrayian_app"))
                conn.execute(text("SELECT set_config('app.current_tenant_id', '', true)"))
                conn.execute(text("SELECT set_config('app.lead_intake', '', true)"))
                assert conn.execute(text("SELECT count(*) FROM lead_form_receipts")).scalar() == 0
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
