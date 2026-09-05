from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.providers.lead_discovery import get_lead_discovery_provider
from app.schemas.common import Envelope
from app.schemas.discovery import DiscoveryHealthOut, DiscoveryRunIn, DiscoveryRunOut
from app.services.discovery import run_discovery
from app.services.orchestrator import process_pending_events

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/health", response_model=Envelope[DiscoveryHealthOut])
def discovery_health(
    ctx: Annotated[AuthContext, Depends(require_permission("leads.read"))],
) -> Envelope[DiscoveryHealthOut]:
    _ = ctx
    return Envelope(data=DiscoveryHealthOut.model_validate(get_lead_discovery_provider().health()))


@router.post("/run", response_model=Envelope[DiscoveryRunOut])
def discover_leads(
    body: DiscoveryRunIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("leads.write"))],
) -> Envelope[DiscoveryRunOut]:
    result = run_discovery(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        profile_urls=body.profile_urls,
        search_query=body.search_query,
        correlation_id=ctx.correlation_id,
    )
    process_pending_events(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data=DiscoveryRunOut.model_validate(result))
