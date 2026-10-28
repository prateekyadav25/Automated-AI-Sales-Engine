"""Local Meta lead-form mapping and a durable notification receipt.

A receipt can arrive before any workspace owns the form, so its tenant is
optional until a single local mapping is found. The mapping is never taken
from the notification body.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class LeadFormBinding(Base, TenantOwnedMixin):
    """One provider form, bound to one tenant and one operating plan."""

    __tablename__ = "lead_form_bindings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "page_id", "form_id", name="uq_lead_form_binding"),
    )

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    page_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    form_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    operating_plan_id: Mapped[UUID] = mapped_column(ForeignKey("operating_plans.id"), index=True, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    field_map_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    permission_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    form_purpose: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class LeadFormReceipt(Base):
    """A verified provider notification, stored before it is acknowledged."""

    __tablename__ = "lead_form_receipts"
    __table_args__ = (UniqueConstraint("provider", "provider_lead_id", name="uq_lead_form_receipt"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_lead_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    form_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    ad_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    adgroup_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider_campaign_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    attribution: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    notification_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    permission_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    answers_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="received", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    binding_id: Mapped[UUID | None] = mapped_column(ForeignKey("lead_form_bindings.id"), nullable=True)
    capture_id: Mapped[UUID | None] = mapped_column(ForeignKey("inbound_captures.id"), nullable=True)
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    operating_plan_id: Mapped[UUID | None] = mapped_column(ForeignKey("operating_plans.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
