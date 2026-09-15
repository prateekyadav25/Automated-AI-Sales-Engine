from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin, TimestampMixin


class AutopilotSettingsVersion(Base, TenantOwnedMixin):
    __tablename__ = "autopilot_settings_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "version", name="uq_autopilot_settings_version"),)

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)


class WhatsAppTemplate(Base, TenantOwnedMixin):
    __tablename__ = "whatsapp_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "template_id", "language", name="uq_whatsapp_template"),)

    template_id: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    variables_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)


class DataQualityIssue(Base, TenantOwnedMixin):
    __tablename__ = "data_quality_issues"
    __table_args__ = (UniqueConstraint("tenant_id", "entity_type", "entity_id", "code", name="uq_data_quality_issue"),)

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)


class OperatorBrief(Base, TenantOwnedMixin):
    __tablename__ = "operator_briefs"

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class ManualOverride(Base, TenantOwnedMixin):
    __tablename__ = "manual_overrides"

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    field_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    previous_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    new_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SchedulerHeartbeat(Base, TimestampMixin):
    __tablename__ = "scheduler_heartbeats"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_beat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ReadinessNotification(Base, TenantOwnedMixin):
    __tablename__ = "readiness_notifications"
    __table_args__ = (UniqueConstraint("tenant_id", "task_key", name="uq_readiness_notification"),)

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(40), default="DATA_COLLECTION", nullable=False)
    new_status: Mapped[str] = mapped_column(String(40), nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
