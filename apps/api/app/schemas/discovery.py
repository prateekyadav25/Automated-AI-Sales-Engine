from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class DiscoveryRunIn(APIModel):
    profile_urls: list[str] = Field(default_factory=list)
    search_query: str = ""
    operating_plan_id: UUID | None = None
    icp_id: UUID | None = None


class DiscoveryProspectOut(APIModel):
    lead_id: str
    name: str = ""
    outcome: str = ""
    coverage_known: int = 0
    coverage_required: int = 5
    confidence: str = "none"
    response_eligible: bool = False
    next_action: str = ""
    explanation: str = ""
    owner_name: str = ""
    provider_ref: str = ""
    product_name: str = ""
    offer_label: str = ""
    enrichment_state: str = ""
    missing_information: str = ""
    eligibility: str = ""
    approval_id: str = ""


class DiscoveryRunOut(APIModel):
    created: int
    skipped: dict[str, int]
    lead_ids: list[str]
    prospects: list[DiscoveryProspectOut] = Field(default_factory=list)
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    failure_class: str = ""
    candidate_count: int
    icp_name: str
    icp_id: str = ""
    operating_plan_id: str = ""
    product_id: str = ""
    filters: dict = Field(default_factory=dict)
    next_action: str = ""


class DiscoveryHealthOut(APIModel):
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    actor_id: str = ""
