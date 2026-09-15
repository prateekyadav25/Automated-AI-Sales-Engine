from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.ai import AIApproval
from app.schemas.common import Envelope, Meta
from app.schemas.providers import ProviderActionOut
from app.services.ads import execute_ads_spend
from app.services.provider_ops import cancel_action, list_actions, retry_action
from app.services.voice import execute_voice_dial

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/actions", response_model=Envelope[list[ProviderActionOut]])
def list_provider_actions(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.read"))],
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> Envelope[list[ProviderActionOut]]:
    rows, total = list_actions(db, tenant_id=ctx.tenant_id, status=status, page=page, page_size=page_size)
    return Envelope(
        data=[ProviderActionOut.model_validate(row) for row in rows],
        meta=Meta(page=page, page_size=page_size, total=total),
    )


@router.post("/actions/{action_id}/retry", response_model=Envelope[ProviderActionOut])
def retry_provider_action(
    action_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.write"))],
) -> Envelope[ProviderActionOut]:
    row = retry_action(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action_id=action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Provider action not found")
    if row.action_type in {"ads.launch", "ads.spend"} and row.approval_id:
        approval = db.get(AIApproval, row.approval_id)
        if approval is not None:
            execute_ads_spend(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, approval=approval)
    if row.action_type == "voice.dial" and row.approval_id:
        approval = db.get(AIApproval, row.approval_id)
        if approval is not None:
            execute_voice_dial(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, approval=approval)
    db.commit()
    db.refresh(row)
    return Envelope(data=ProviderActionOut.model_validate(row))


@router.post("/actions/{action_id}/cancel", response_model=Envelope[ProviderActionOut])
def cancel_provider_action(
    action_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("autonomy.write"))],
) -> Envelope[ProviderActionOut]:
    row = cancel_action(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action_id=action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Provider action not found")
    db.commit()
    db.refresh(row)
    return Envelope(data=ProviderActionOut.model_validate(row))
