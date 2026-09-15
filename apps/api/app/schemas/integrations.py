from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class IntegrationAccountOut(APIModel):
    id: UUID
    provider: str
    provider_account_id: str
    connected_user_id: UUID | None = None
    account_key: str = "default"
    status: str
    scopes: list[str] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    last_sync_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str = ""


class GoogleConnectOut(APIModel):
    authorization_url: str
    configured: bool


class InboxSimulateIn(APIModel):
    from_addr: str
    to_addrs: list[str] = Field(default_factory=list)
    subject: str = ""
    body_text: str
    thread_id: str = ""
    provider_message_id: str = ""


class InboxSimulateOut(APIModel):
    event_id: UUID
    message_id: UUID | None = None
    processed: str


class CalendarBookIn(APIModel):
    lead_id: UUID
    start_at: datetime
    end_at: datetime
    timezone: str = "UTC"
    title: str = ""


class CalendarBookOut(APIModel):
    approval_id: UUID
    status: str


class ConnectorOut(APIModel):
    provider: str
    name: str
    state: str
    live_enabled: bool
    webhook_url: str = ""
    last_sync_at: datetime | None = None
    connected_customers: int = 0
    stale_customers: int = 0
    failed_syncs: int = 0
    last_error: str = ""


class EntityMappingOut(APIModel):
    id: UUID
    provider: str
    entity_type: str
    external_id: str
    internal_entity_type: str
    internal_entity_id: str
    status: str
    confidence: int
    evidence: dict = Field(default_factory=dict)
    last_verified_at: datetime | None = None


class EntityMappingChangeIn(APIModel):
    internal_entity_type: str
    internal_entity_id: str
