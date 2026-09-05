from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag import ingest_text, retrieve
from app.ai.runtime import draft_email, meeting_prep, research_account, run_copilot, summarize_entity
from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.ai import AIApproval, KnowledgeSource
from app.schemas.ai import (
    ApprovalDecision,
    ApprovalOut,
    CopilotRequest,
    CopilotResponse,
    EmailDraftRequest,
    EmailDraftResponse,
    KnowledgeHit,
    KnowledgeUploadResponse,
)
from app.schemas.common import Envelope, Meta
from app.services.approval_view import approval_out
from app.services.approvals import apply_approval_decision
from app.services.audit import write_audit
from app.services.query import get_owned

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/copilot/chat", response_model=Envelope[CopilotResponse])
def copilot_chat(
    body: CopilotRequest,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ai.copilot"))],
) -> Envelope[CopilotResponse]:
    result = run_copilot(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        permissions=ctx.permissions,
        message=body.message,
        conversation_id=body.conversation_id,
        correlation_id=ctx.correlation_id,
    )
    return Envelope(data=CopilotResponse(**result))


@router.post("/meeting-prep/accounts/{account_id}")
def meeting_prep_account(
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ai.research"))],
) -> Envelope[dict]:
    return Envelope(
        data=meeting_prep(
            db,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user.id,
            permissions=ctx.permissions,
            account_id=account_id,
        )
    )


@router.post("/research/accounts/{account_id}")
def research(
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ai.research"))],
) -> Envelope[dict]:
    data = research_account(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        permissions=ctx.permissions,
        account_id=account_id,
    )
    db.commit()
    return Envelope(data=data)


@router.post("/summaries/{entity_type}/{entity_id}")
def summaries(
    entity_type: str,
    entity_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ai.copilot"))],
) -> Envelope[dict]:
    return Envelope(
        data=summarize_entity(
            db,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user.id,
            permissions=ctx.permissions,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    )


@router.post("/drafts/email", response_model=Envelope[EmailDraftResponse])
def email_draft(
    body: EmailDraftRequest,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ai.draft"))],
) -> Envelope[EmailDraftResponse]:
    result = draft_email(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        permissions=ctx.permissions,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        intent=body.intent,
        send=body.send,
    )
    return Envelope(data=EmailDraftResponse(**result))


@router.post("/knowledge", response_model=Envelope[KnowledgeUploadResponse])
async def upload_knowledge(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("knowledge.write"))],
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> Envelope[KnowledgeUploadResponse]:
    raw = await file.read()
    if len(raw) > 1_000_000:
        raise HTTPException(status_code=413, detail="File too large")
    text = raw.decode("utf-8", errors="ignore")
    source = ingest_text(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, title=title, text=text)
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="knowledge.upload",
        entity_type="knowledge_source",
        entity_id=str(source.id),
        after={"title": title},
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(source)
    from sqlalchemy import func

    from app.models.ai import KnowledgeChunk

    chunk_count = db.scalar(
        select(func.count()).where(
            KnowledgeChunk.source_id == source.id, KnowledgeChunk.tenant_id == ctx.tenant_id
        )
    ) or 0
    return Envelope(data=KnowledgeUploadResponse(id=source.id, title=source.title, chunks=int(chunk_count)))


@router.get("/knowledge", response_model=Envelope[list[dict]])
def list_knowledge(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("knowledge.read"))],
) -> Envelope[list[dict]]:
    rows = db.scalars(
        select(KnowledgeSource).where(
            KnowledgeSource.tenant_id == ctx.tenant_id, KnowledgeSource.deleted_at.is_(None)
        )
    ).all()
    return Envelope(
        data=[{"id": str(row.id), "title": row.title, "status": row.status} for row in rows],
        meta=Meta(total=len(rows)),
    )


@router.get("/knowledge/search", response_model=Envelope[list[KnowledgeHit]])
def search_knowledge(
    q: str,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("knowledge.read"))],
) -> Envelope[list[KnowledgeHit]]:
    hits = retrieve(db, tenant_id=ctx.tenant_id, query=q)
    return Envelope(data=[KnowledgeHit(**hit) for hit in hits], meta=Meta(total=len(hits)))


@router.get("/approvals", response_model=Envelope[list[ApprovalOut]])
def list_approvals(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ai.approvals.read"))],
) -> Envelope[list[ApprovalOut]]:
    rows = db.scalars(
        select(AIApproval)
        .where(AIApproval.tenant_id == ctx.tenant_id, AIApproval.deleted_at.is_(None))
        .order_by(AIApproval.created_at.desc())
    ).all()
    return Envelope(data=[approval_out(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/approvals/{approval_id}/decide", response_model=Envelope[ApprovalOut])
def decide_approval(
    approval_id: UUID,
    body: ApprovalDecision,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ai.approvals.decide"))],
) -> Envelope[ApprovalOut]:
    row = get_owned(db, AIApproval, ctx.tenant_id, approval_id)
    if body.decision not in {"approve", "reject"}:
        raise HTTPException(status_code=422, detail="decision must be approve or reject")
    apply_approval_decision(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        row=row,
        decision=body.decision,
        note=body.note,
        payload_patch=body.payload_patch,
        pause_automation=body.pause_entity,
    )
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="ai.approval.decide",
        entity_type="ai_approval",
        entity_id=str(row.id),
        after={"status": row.status},
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=approval_out(row))
