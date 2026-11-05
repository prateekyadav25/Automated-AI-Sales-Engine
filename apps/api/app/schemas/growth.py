from uuid import UUID

from pydantic import BaseModel, Field


class AnalyzeIn(BaseModel):
    website_url: str = ""


class BrandSettingsIn(BaseModel):
    website_url: str | None = None
    ga4_property_id: str | None = Field(default=None, max_length=40)


class BrandFactIn(BaseModel):
    category: str
    statement: str = Field(min_length=2, max_length=2000)
    source_url: str = ""
    evidence: str = ""
    approve: bool = False


class FactReviewIn(BaseModel):
    fact_ids: list[UUID] = Field(min_length=1, max_length=200)
    decision: str
    note: str = ""


class CompetitorsIn(BaseModel):
    usernames: list[str] = Field(default_factory=list, max_length=10)
    refresh: bool = False


class GrowthAccountIn(BaseModel):
    platform: str
    external_id: str
    access_token: str = Field(min_length=10, max_length=4000)
    page_id: str = ""
    name: str = ""
    username: str = ""
    timezone: str = "UTC"


class FixtureAccountIn(BaseModel):
    platform: str
    name: str = ""


class PostingWindow(BaseModel):
    days: list[int]
    start: str
    end: str


class AccountUpdateIn(BaseModel):
    posting_windows: list[PostingWindow] | None = None
    daily_cap: int | None = None
    timezone: str | None = None


class PillarIn(BaseModel):
    key: str
    name: str
    description: str = ""
    fact_ids: list[str] = Field(default_factory=list)


class CadenceIn(BaseModel):
    formats: dict[str, int] = Field(default_factory=dict)


class StrategyIn(BaseModel):
    objective: str = ""
    optimization_metric: str = "reach"
    pillars: list[PillarIn] = Field(default_factory=list)
    audiences: list[str] = Field(default_factory=list)
    cadence: dict[str, CadenceIn] = Field(default_factory=dict)
    call_to_action: str = ""
    destination_kind: str = "form"
    destination_form_key_id: UUID | None = None
    destination_url: str = ""
    auto_create: bool = True
    auto_schedule: bool = False
    review_terms: list[str] | None = None
    horizon_days: int = 30


class PauseIn(BaseModel):
    paused: bool


class EventIn(BaseModel):
    title: str
    kind: str = "event"
    starts_on: str
    ends_on: str
    details: str = ""
    fact_ids: list[str] = Field(default_factory=list)
    source_url: str = ""


class SkipIn(BaseModel):
    reason: str = ""


class CaptionIn(BaseModel):
    caption: str = Field(min_length=1, max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)


class ReviewIn(BaseModel):
    decision: str
    note: str = ""


class GrowthGrantIn(BaseModel):
    platform: str
    volume_cap: int
    days: int
    name: str = ""


class ResolveIn(BaseModel):
    decision: str
    external_id: str = ""
    note: str = ""


class DecideIn(BaseModel):
    decision: str
