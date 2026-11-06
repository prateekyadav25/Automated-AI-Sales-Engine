from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.schemas.channel_search import (
    ChannelSearchIn,
    ChannelSearchOut,
    ChannelSearchStatusOut,
    SnippetExpandIn,
    SnippetExpandOut,
)
from app.schemas.common import Envelope, Meta
from app.services.channel_search import (
    begin_channel_search,
    channel_search_status,
    hits_for_search,
    list_channel_searches,
    mark_channel_search_failed,
    present_search,
    run_channel_search,
)
from app.services.snippet_expand import SnippetNotFound, SnippetUnavailable, expand_snippet
from app.workers.celery_app import finish_channel_search_task

router = APIRouter(prefix="/channel-search", tags=["channel-search"])


@router.get("/status", response_model=Envelope[ChannelSearchStatusOut])
def read_channel_search_status(
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
) -> Envelope[ChannelSearchStatusOut]:
    _ = ctx
    return Envelope(data=ChannelSearchStatusOut.model_validate(channel_search_status()))


@router.get("", response_model=Envelope[list[ChannelSearchOut]])
def read_channel_searches(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> Envelope[list[ChannelSearchOut]]:
    rows = list_channel_searches(db, ctx.tenant_id, limit=limit)
    return Envelope(data=[ChannelSearchOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/snippet", response_model=Envelope[SnippetExpandOut])
def read_snippet_detail(
    body: SnippetExpandIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
) -> Envelope[SnippetExpandOut]:
    try:
        text = expand_snippet(db, ctx.tenant_id, body.url)
    except SnippetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SnippetUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Envelope(data=SnippetExpandOut(text=text))


@router.post("", response_model=Envelope[ChannelSearchOut])
def create_channel_search(
    body: ChannelSearchIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[ChannelSearchOut]:
    if get_settings().channel_search_background:
        row = begin_channel_search(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, query=body.query)
        db.commit()
        db.refresh(row)
        try:
            finish_channel_search_task.delay(str(row.id), str(ctx.tenant_id))
        except Exception as exc:
            mark_channel_search_failed(db, row.id)
            db.commit()
            raise HTTPException(status_code=503, detail="The search could not be started.") from exc
        payload = present_search(row, [])
        return Envelope(data=ChannelSearchOut.model_validate(payload))
    row = run_channel_search(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, query=body.query)
    db.commit()
    db.refresh(row)
    payload = present_search(row, hits_for_search(db, ctx.tenant_id, row.id))
    return Envelope(data=ChannelSearchOut.model_validate(payload))
