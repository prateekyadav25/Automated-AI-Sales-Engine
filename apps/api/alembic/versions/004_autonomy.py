"""Autonomy, ads launch, and voice gates.

Revision ID: 004
Revises: 003
Create Date: 2026-08-22
"""

from alembic import op

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    return
