from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class InboundCapture(Base, TenantOwnedMixin):
    __tablename__ = "inbound_captures"

    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id"), index=True, nullable=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="inbound", nullable=False)
    channel: Mapped[str] = mapped_column(String(80), default="website", nullable=False)
    campaign: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    ad_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    creative: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    keyword: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    landing_page: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    utm_source: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    utm_medium: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    utm_campaign: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    device: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    consent_email: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="accepted", nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DedupeReview(Base, TenantOwnedMixin):
    __tablename__ = "dedupe_reviews"

    left_type: Mapped[str] = mapped_column(String(40), nullable=False)
    left_id: Mapped[str] = mapped_column(String(64), nullable=False)
    right_type: Mapped[str] = mapped_column(String(40), nullable=False)
    right_id: Mapped[str] = mapped_column(String(64), nullable=False)
    match_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
