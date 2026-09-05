from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class WorkflowDefinition(Base, TenantOwnedMixin):
    __tablename__ = "workflow_definitions"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger_event: Mapped[str] = mapped_column(String(80), nullable=False)
    condition_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    actions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class WorkflowRun(Base, TenantOwnedMixin):
    __tablename__ = "workflow_runs"

    definition_id: Mapped[UUID | None] = mapped_column(nullable=True)
    trigger_event: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    log_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
