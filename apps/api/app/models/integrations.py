from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class ProviderAccount(Base, TenantOwnedMixin):
    __tablename__ = "provider_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "account_key", name="uq_provider_account_key"),)

    provider: Mapped[str] = mapped_column(String(40), default="google", nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    account_key: Mapped[str] = mapped_column(String(120), default="default", nullable=False)
    connected_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="disconnected", nullable=False)
    scopes: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_history_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)


class EmailMessage(Base, TenantOwnedMixin):
    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "provider_message_id", name="uq_email_provider_message"),)

    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    from_addr: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    to_addrs: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    subject: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    body_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="mock-email", nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_thread_id: Mapped[str] = mapped_column(String(200), default="", index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_approvals.id"), nullable=True)
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classification: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    classification_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ProviderInboxEvent(Base, TenantOwnedMixin):
    __tablename__ = "provider_inbox_events"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "external_id", name="uq_provider_inbox_external"),)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ProviderAction(Base, TenantOwnedMixin):
    __tablename__ = "provider_actions"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_provider_action_idempotency"),)

    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    approval_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_approvals.id"), nullable=True)
    run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), default="", index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED", nullable=False)
    failure_class: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    request_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    response_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provider_mode: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    provider_account_id: Mapped[UUID | None] = mapped_column(nullable=True)
    policy_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class WebhookRoute(Base, TenantOwnedMixin):
    __tablename__ = "webhook_routes"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", name="uq_webhook_route_provider"),)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)


class ProviderHealthState(Base, TenantOwnedMixin):
    __tablename__ = "provider_health_states"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", name="uq_provider_health_tenant"),)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
