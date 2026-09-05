from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class SignalMixin(TenantOwnedMixin):
    source: Mapped[str] = mapped_column(String(80), default="mock", nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    impact: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_mock: Mapped[bool] = mapped_column(default=True, nullable=False)


class Market(Base, TenantOwnedMixin):
    __tablename__ = "markets"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    industry: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    geography: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attractiveness: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ai_readiness: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    technology_readiness: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    budget_potential: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    growth_potential: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    competitive_intensity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    procurement_probability: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    buying_timing: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score_reasons: Mapped[str] = mapped_column(Text, default="", nullable=False)
    score_version: Mapped[str] = mapped_column(String(20), default="rules-v1", nullable=False)


class MarketSignal(Base, SignalMixin):
    __tablename__ = "market_signals"

    market_id: Mapped[UUID] = mapped_column(ForeignKey("markets.id"), index=True, nullable=False)
    signal_type: Mapped[str] = mapped_column(String(40), default="general", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)


class AccountSignal(Base, SignalMixin):
    __tablename__ = "account_signals"

    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    signal_type: Mapped[str] = mapped_column(String(40), default="general", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)


class TechnologySignal(Base, SignalMixin):
    __tablename__ = "technology_signals"

    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=True)
    technology: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="", nullable=False)


class IntentSignal(Base, SignalMixin):
    __tablename__ = "intent_signals"

    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=True)
    topic: Mapped[str] = mapped_column(String(160), nullable=False)
    intensity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CompetitiveSignal(Base, SignalMixin):
    __tablename__ = "competitive_signals"

    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=True)
    competitor: Mapped[str] = mapped_column(String(160), nullable=False)
    movement: Mapped[str] = mapped_column(String(80), default="mentioned", nullable=False)


class TriggerEvent(Base, SignalMixin):
    __tablename__ = "trigger_events"

    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
