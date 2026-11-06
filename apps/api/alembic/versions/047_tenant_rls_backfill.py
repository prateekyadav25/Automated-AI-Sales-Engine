"""Force tenant row-level security on the 039–045 tables that were created without it.

Revision ID: 047
Revises: 046

Downgrade is a no-op. Restoring the pre-047 backup returns the database to 046.
Lead-form receipts can arrive before a workspace owns the form, so the webhook
and its worker set app.lead_intake. A normal request does not, and cannot read
another workspace's rows.
"""

from sqlalchemy import inspect, text

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None

_TENANT_TABLES = (
    "content_proposals",
    "content_recommendations",
    "deal_purchases",
    "onboarding_completions",
    "organic_metric_observations",
    "paid_ads",
    "purchase_health_signals",
    "quote_acceptances",
)
_TENANT_USING = "tenant_id::text = current_setting('app.current_tenant_id', true)"
_INTAKE = "current_setting('app.lead_intake', true) = '1'"
_NO_TENANT = "current_setting('app.current_tenant_id', true) = ''"
_BINDING_USING = f"{_TENANT_USING} OR {_INTAKE}"
_RECEIPT_USING = f"{_TENANT_USING} OR {_INTAKE}"
_RECEIPT_CHECK = f"{_TENANT_USING} OR ({_INTAKE} AND ({_NO_TENANT} OR {_TENANT_USING}))"


def _enable_rls(conn, table: str, using_sql: str, check_sql: str | None = None) -> None:
    check = check_sql or using_sql
    conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
    conn.execute(text(f'CREATE POLICY tenant_isolation ON "{table}" USING ({using_sql}) WITH CHECK ({check})'))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    names = set(inspect(bind).get_table_names())
    for table in _TENANT_TABLES:
        if table in names:
            _enable_rls(bind, table, _TENANT_USING)
    if "lead_form_bindings" in names:
        _enable_rls(bind, "lead_form_bindings", _BINDING_USING, _TENANT_USING)
    if "lead_form_receipts" in names:
        _enable_rls(bind, "lead_form_receipts", _RECEIPT_USING, _RECEIPT_CHECK)


def downgrade() -> None:
    return
