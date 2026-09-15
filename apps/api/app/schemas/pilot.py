from datetime import datetime
from uuid import UUID

from app.schemas.common import APIModel


class PilotCheckOut(APIModel):
    key: str
    state: str
    detail: str
    required: bool


class PilotReadinessOut(APIModel):
    operating_mode: str
    environment: str
    can_activate_pilot: bool
    can_activate_production: bool
    blockers: list[str]
    items: list[PilotCheckOut]


class PilotActivateIn(APIModel):
    target: str
    reason: str = ""


class PilotActivateOut(APIModel):
    operating_mode: str


class CloseLostIn(APIModel):
    reason: str
    note: str = ""


class ChurnIn(APIModel):
    reason: str


class ExpansionOutcomeIn(APIModel):
    status: str
    value: float | None = None
    product: str = ""


class HealthRebuildIn(APIModel):
    customer_id: UUID | None = None


class OverrideIn(APIModel):
    entity_type: str
    entity_id: str
    field_name: str = ""
    previous: dict = {}
    new: dict = {}
    reason: str = ""


class UsefulIn(APIModel):
    useful: str


class CredentialIn(APIModel):
    provider: str
    access_token: str
    account_key: str = "default"
    extra: dict = {}


class WhatsAppTemplateIn(APIModel):
    template_id: str
    language: str = "en"
    status: str = "pending"
    variables: list[str] = []
    body: str = ""


class WhatsAppTemplateOut(APIModel):
    id: UUID
    template_id: str
    language: str
    status: str
    body: str


class BriefOut(APIModel):
    id: UUID
    kind: str
    payload: dict
    period_start: datetime | None = None
    period_end: datetime | None = None


class HealthRebuildOut(APIModel):
    rebuilt: int
