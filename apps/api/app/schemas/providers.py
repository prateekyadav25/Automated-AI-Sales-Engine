from datetime import datetime
from uuid import UUID

from app.schemas.common import APIModel


class ProviderActionOut(APIModel):
    id: UUID
    action_type: str
    provider: str
    status: str
    failure_class: str = ""
    external_id: str = ""
    entity_type: str = ""
    entity_id: str = ""
    approval_id: UUID | None = None
    attempts: int = 0
    last_error: str = ""
    request_summary: str = ""
    response_summary: str = ""
    created_at: datetime
    updated_at: datetime | None = None
    next_retry_at: datetime | None = None
