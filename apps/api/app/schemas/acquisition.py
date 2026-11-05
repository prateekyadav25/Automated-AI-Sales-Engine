from datetime import datetime
from uuid import UUID

from app.schemas.common import APIModel
from app.schemas.crm import LeadOut


class CaptureIn(APIModel):
    first_name: str
    last_name: str
    email: str
    company_name: str = ""
    title: str = ""
    source: str = "inbound"
    channel: str = "website"
    campaign: str = ""
    ad_name: str = ""
    creative: str = ""
    keyword: str = ""
    landing_page: str = ""
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""
    device: str = ""
    consent_email: bool = False
    phone: str = ""
    request_note: str = ""
    campaign_id: UUID | None = None
    ad_id: str = ""
    ad: str = ""
    publication: str = ""
    growth: str = ""


class CaptureOut(APIModel):
    id: UUID
    lead_id: UUID | None
    email: str
    company_name: str
    source: str
    channel: str
    campaign: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    landing_page: str
    consent_email: bool
    phone: str = ""
    request_note: str = ""
    status: str
    captured_at: datetime | None
    campaign_id: UUID | None = None
    ad_id: str = ""


class CaptureResult(APIModel):
    capture: CaptureOut
    lead: LeadOut | None
    reviews_opened: int


class DedupeOut(APIModel):
    id: UUID
    left_type: str
    left_id: str
    right_type: str
    right_id: str
    match_kind: str
    confidence: int
    reason: str
    status: str


class DedupeDecision(APIModel):
    decision: str


class PublicFormField(APIModel):
    key: str
    label: str
    type: str
    required: bool = False
    placeholder: str = ""
    options: list[str] = []


class PublicFormOut(APIModel):
    id: UUID
    name: str
    status: str
    url: str = ""
    last_used_at: datetime | None = None
    fields: list[PublicFormField] = []


class PublicFormIn(APIModel):
    name: str = ""
    fields: list[PublicFormField] = []


class PublicFormPatch(APIModel):
    name: str
    fields: list[PublicFormField]


class AcquisitionOverview(APIModel):
    captures: int
    accepted: int
    duplicate_review: int
    pending_dedupe: int
