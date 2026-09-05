"""Lifecycle engines for phases 9-22.

Revision ID: 003
Revises: 002
Create Date: 2026-08-19
"""

from alembic import op

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    return
