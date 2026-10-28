"""Store Meta lead-form mappings and notification receipts.

Revision ID: 040
Revises: 039

Downgrade is a no-op. It does not drop the new tables.
"""

from sqlalchemy import text

from alembic import op
from app.db.base import Base
from app.models import *  # noqa: F403

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agrayian_app"))


def downgrade() -> None:
    return
