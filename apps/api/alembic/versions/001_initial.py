"""Initial schema via SQLAlchemy metadata.

Revision ID: 001
Revises:
Create Date: 2026-08-18
"""

from alembic import op

from app.db.base import Base
from app.models import *  # noqa: F403

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
