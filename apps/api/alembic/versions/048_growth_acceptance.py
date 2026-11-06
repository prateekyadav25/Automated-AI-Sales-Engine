"""Acceptance authorizations for live Social Growth checks.

Revision ID: 048
Revises: 047

The table stores a person's approval. It does not store a verified result.
Downgrade is a no-op. Restoring the pre-048 backup returns the database to 047.
"""

from sqlalchemy import inspect, text

from alembic import op
from app.db.base import Base
from app.models.growth import GrowthAcceptanceGate

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None

_USING = "tenant_id::text = current_setting('app.current_tenant_id', true)"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    Base.metadata.create_all(bind, tables=[GrowthAcceptanceGate.__table__], checkfirst=True)
    if "growth_acceptance_gates" not in set(inspect(bind).get_table_names()):
        return
    bind.execute(text('ALTER TABLE "growth_acceptance_gates" ENABLE ROW LEVEL SECURITY'))
    bind.execute(text('ALTER TABLE "growth_acceptance_gates" FORCE ROW LEVEL SECURITY'))
    bind.execute(text('DROP POLICY IF EXISTS tenant_isolation ON "growth_acceptance_gates"'))
    bind.execute(text(f'CREATE POLICY tenant_isolation ON "growth_acceptance_gates" USING ({_USING}) WITH CHECK ({_USING})'))
    bind.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON growth_acceptance_gates TO agrayian_app"))


def downgrade() -> None:
    return
