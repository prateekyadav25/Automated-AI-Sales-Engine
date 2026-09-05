from uuid import UUID

from app.schemas.common import APIModel


class CopilotRequest(APIModel):
    message: str
    conversation_id: UUID | None = None


class CopilotResponse(APIModel):
    conversation_id: UUID
    reply: str
    citations: list[dict] = []
    provider: str
    is_mock: bool
    approval_id: UUID | None = None


class EmailDraftRequest(APIModel):
    entity_type: str
    entity_id: UUID
    intent: str = "follow_up"
    send: bool = False


class EmailDraftResponse(APIModel):
    recommendation_id: UUID
    subject: str
    body: str
    approval_id: UUID | None = None
    provider: str
    is_mock: bool


class KnowledgeUploadResponse(APIModel):
    id: UUID
    title: str
    chunks: int


class KnowledgeHit(APIModel):
    chunk_id: str
    source_id: str
    title: str
    text: str
    score: float


class ApprovalOut(APIModel):
    id: UUID
    action_level: int
    action_type: str
    title: str
    payload_json: str
    status: str
    decision_note: str = ""
    run_id: UUID | None = None
    entity_type: str = ""
    entity_id: str = ""
    who: str = ""
    why: str = ""
    evidence: str = ""
    risk: str = ""
    expected_outcome: str = ""
    message: str = ""
    commercial_impact: str = ""
    budget_impact: str = ""


class ApprovalDecision(APIModel):
    decision: str
    note: str = ""
    payload_patch: dict | None = None
    pause_entity: bool = False
