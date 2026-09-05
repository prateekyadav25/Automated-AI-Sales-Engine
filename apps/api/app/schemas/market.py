from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class MarketIn(APIModel):
    name: str
    industry: str = ""
    geography: str = ""
    description: str = ""


class MarketOut(MarketIn):
    id: UUID
    attractiveness: int
    ai_readiness: int
    technology_readiness: int
    budget_potential: int
    growth_potential: int
    competitive_intensity: int
    procurement_probability: int
    buying_timing: int
    score_reasons: str
    score_version: str


class SignalOut(APIModel):
    id: UUID
    kind: str
    title: str
    source: str
    evidence: str
    confidence: int
    impact: str
    recommended_action: str
    occurred_at: datetime | None
    is_mock: bool
    account_id: UUID | None = None
    market_id: UUID | None = None
    extra: dict = Field(default_factory=dict)


class TriggerOut(APIModel):
    id: UUID
    account_id: UUID | None
    trigger_type: str
    title: str
    body: str
    source: str
    evidence: str
    confidence: int
    recommended_action: str
    occurred_at: datetime | None
    is_mock: bool


class MarketOverview(APIModel):
    markets: int
    signals: int
    triggers: int
    mock_signals: int
    scored_markets: int


class RefreshOut(APIModel):
    accounts_scanned: int
    created: dict[str, int]
    provider: str
    is_mock: bool
