"""Market intelligence and acquisition tables.

Revision ID: 002
Revises: 001
Create Date: 2026-08-19
"""

from alembic import op

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    return
