from pydantic import Field

from app.schemas.common import APIModel


class DiscoveryRunIn(APIModel):
    profile_urls: list[str] = Field(default_factory=list)
    search_query: str = ""


class DiscoveryRunOut(APIModel):
    created: int
    skipped: dict[str, int]
    lead_ids: list[str]
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    candidate_count: int
    icp_name: str


class DiscoveryHealthOut(APIModel):
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    actor_id: str = ""
