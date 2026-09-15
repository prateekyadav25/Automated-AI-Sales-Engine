import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.ai import AIApproval
from app.models.crm import Customer, Lead
from app.models.identity import Tenant
from app.models.integrations import ProviderAccount
from app.models.signals import ExternalEntityMapping, IntegrationWatermark
from app.providers.email import InboundEmail
from app.schemas.autonomy import ProviderHealthOut
from app.schemas.common import Envelope, Meta
from app.schemas.integrations import (
    CalendarBookIn,
    CalendarBookOut,
    ConnectorOut,
    EntityMappingChangeIn,
    EntityMappingOut,
    GoogleConnectOut,
    InboxSimulateIn,
    InboxSimulateOut,
    IntegrationAccountOut,
)
from app.schemas.pilot import CredentialIn
from app.services.autopilot_settings import get_or_create_settings
from app.services.autopilot_status import provider_health
from app.services.entity_mapping import confirm_mapping, ignore_mapping, list_mappings, unlink_mapping
from app.services.google_oauth import (
    authorization_url,
    disconnect_google,
    exchange_code,
    google_configured,
    read_state,
    upsert_google_account,
)
from app.services.inbox import persist_inbound, record_inbox_event
from app.services.orchestrator import process_pending_events
from app.services.provider_accounts import list_accounts, public_account, upsert_token_account
from app.services.provider_provision import channel_modes, provision_env_credentials
from app.services.query import get_owned
from app.services.webhook_routes import demo_routing_token

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=Envelope[list[IntegrationAccountOut]])
def list_integrations(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.read"))],
) -> Envelope[list[IntegrationAccountOut]]:
    rows = [IntegrationAccountOut.model_validate(public_account(row)) for row in list_accounts(db, ctx.tenant_id)]
    return Envelope(data=rows, meta=Meta(total=len(rows)))


@router.get("/providers", response_model=Envelope[list[ProviderHealthOut]])
def list_provider_health(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.read"))],
) -> Envelope[list[ProviderHealthOut]]:
    rows = provider_health(db, ctx.tenant_id)
    return Envelope(data=rows, meta=Meta(total=len(rows)))


@router.get("/google/connect", response_model=Envelope[GoogleConnectOut])
def google_connect(
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
    capabilities: str = Query(default="mail,calendar"),
) -> Envelope[GoogleConnectOut]:
    if not google_configured():
        raise HTTPException(status_code=409, detail="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required")
    return Envelope(
        data=GoogleConnectOut(
            authorization_url=authorization_url(tenant_id=ctx.tenant_id, user_id=ctx.user.id, capabilities=capabilities),
            configured=True,
        )
    )


@router.get("/google/callback")
def google_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    settings = get_settings()
    dest = f"{settings.web_app_origin.rstrip('/')}/admin/integrations"
    if error or not code or not state:
        return RedirectResponse(f"{dest}?error=oauth_denied")
    try:
        payload = read_state(state)
        token = exchange_code(code)
        upsert_google_account(
            db,
            tenant_id=UUID(str(payload["tenant_id"])),
            user_id=UUID(str(payload["user_id"])),
            token_payload=token,
            requested=list(payload.get("scopes") or []),
        )
        db.commit()
    except Exception:
        return RedirectResponse(f"{dest}?error=oauth_failed")
    return RedirectResponse(f"{dest}?connected=google")


@router.delete("/{account_id}", response_model=Envelope[IntegrationAccountOut])
def disconnect_account(
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
) -> Envelope[IntegrationAccountOut]:
    row = get_owned(db, ProviderAccount, ctx.tenant_id, account_id)
    disconnect_google(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, account=row)
    db.commit()
    db.refresh(row)
    return Envelope(data=IntegrationAccountOut.model_validate(public_account(row)))


@router.post("/inbox/simulate", response_model=Envelope[InboxSimulateOut])
def simulate_inbox(
    body: InboxSimulateIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
) -> Envelope[InboxSimulateOut]:
    external_id = body.provider_message_id or f"sim-{uuid4()}"
    event = record_inbox_event(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        provider="mock-email",
        external_id=external_id,
        payload=body.model_dump(),
    )
    inbound = InboundEmail(
        provider_message_id=external_id,
        thread_id=body.thread_id or f"thread-{uuid4()}",
        from_addr=body.from_addr,
        to_addrs=body.to_addrs,
        subject=body.subject,
        body_text=body.body_text,
        received_at=datetime.now(UTC),
    )
    message = persist_inbound(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, inbound=inbound, provider="mock-email")
    event.processed_at = datetime.now(UTC)
    process_pending_events(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(
        data=InboxSimulateOut(
            event_id=event.id,
            message_id=message.id if message else None,
            processed="processed",
        )
    )


@router.post("/calendar/book", response_model=Envelope[CalendarBookOut])
def queue_calendar_book(
    body: CalendarBookIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("meetings.write"))],
) -> Envelope[CalendarBookOut]:
    lead = get_owned(db, Lead, ctx.tenant_id, body.lead_id)
    key = f"calendar.create:{lead.id}:{body.start_at.isoformat()}"
    existing = db.scalar(
        select(AIApproval).where(
            AIApproval.tenant_id == ctx.tenant_id,
            AIApproval.idempotency_key == key,
            AIApproval.deleted_at.is_(None),
        )
    )
    if existing is None:
        existing = AIApproval(
            tenant_id=ctx.tenant_id,
            created_by=ctx.user.id,
            action_level=2,
            action_type="calendar.create",
            title=f"Book meeting with {lead.email}",
            payload_json=json.dumps(
                {
                    "lead_id": str(lead.id),
                    "start_at": body.start_at.isoformat(),
                    "end_at": body.end_at.isoformat(),
                    "timezone": body.timezone,
                    "title": body.title or f"Meeting with {lead.email}",
                }
            ),
            status="pending",
            entity_type="lead",
            entity_id=str(lead.id),
            idempotency_key=key,
        )
        db.add(existing)
        db.flush()
    db.commit()
    db.refresh(existing)
    return Envelope(data=CalendarBookOut(approval_id=existing.id, status=existing.status))


def _mapping_out(row) -> EntityMappingOut:
    try:
        evidence = json.loads(row.evidence_json or "{}")
    except json.JSONDecodeError:
        evidence = {}
    return EntityMappingOut(
        id=row.id,
        provider=row.provider,
        entity_type=row.entity_type,
        external_id=row.external_id,
        internal_entity_type=row.internal_entity_type,
        internal_entity_id=row.internal_entity_id,
        status=row.status,
        confidence=row.confidence,
        evidence=evidence if isinstance(evidence, dict) else {},
        last_verified_at=row.last_verified_at,
    )


@router.get("/connectors", response_model=Envelope[list[ConnectorOut]])
def list_connectors(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.read"))],
) -> Envelope[list[ConnectorOut]]:
    settings = get_or_create_settings(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    tenant = db.get(Tenant, ctx.tenant_id)
    slug = tenant.slug if tenant else "tenant"
    flags = {
        "usage": settings.usage_live_enabled,
        "support": settings.support_live_enabled,
        "finance": settings.finance_live_enabled,
        "erp": settings.erp_live_enabled,
    }
    rows = []
    for provider, name in (("usage", "Usage"), ("support", "Support"), ("finance", "Finance"), ("erp", "ERP")):
        mark = db.scalar(
            select(IntegrationWatermark).where(
                IntegrationWatermark.tenant_id == ctx.tenant_id,
                IntegrationWatermark.provider == provider,
                IntegrationWatermark.deleted_at.is_(None),
            )
        )
        token = demo_routing_token(slug, provider)
        rows.append(
            ConnectorOut(
                provider=provider,
                name=name,
                state="LIVE" if flags[provider] else "NOT_CONNECTED",
                live_enabled=flags[provider],
                webhook_url=f"/api/v1/webhooks/{provider}/{token}",
                last_sync_at=mark.last_sync_at if mark else None,
                connected_customers=mark.connected_customers if mark else 0,
                stale_customers=mark.stale_customers if mark else 0,
                failed_syncs=mark.failed_syncs if mark else 0,
                last_error=mark.last_error if mark else "",
            )
        )
    return Envelope(data=rows, meta=Meta(total=len(rows)))


@router.get("/mappings", response_model=Envelope[list[EntityMappingOut]])
def list_entity_mappings(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.read"))],
    status: str | None = None,
) -> Envelope[list[EntityMappingOut]]:
    rows = list_mappings(db, ctx.tenant_id, status=status)
    return Envelope(data=[_mapping_out(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/mappings/{mapping_id}/confirm", response_model=Envelope[EntityMappingOut])
def confirm_entity_mapping(
    mapping_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
) -> Envelope[EntityMappingOut]:
    row = get_owned(db, ExternalEntityMapping, ctx.tenant_id, mapping_id)
    confirm_mapping(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, mapping=row)
    db.commit()
    db.refresh(row)
    return Envelope(data=_mapping_out(row))


@router.post("/mappings/{mapping_id}/ignore", response_model=Envelope[EntityMappingOut])
def ignore_entity_mapping(
    mapping_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
) -> Envelope[EntityMappingOut]:
    row = get_owned(db, ExternalEntityMapping, ctx.tenant_id, mapping_id)
    ignore_mapping(db, mapping=row)
    db.commit()
    db.refresh(row)
    return Envelope(data=_mapping_out(row))


@router.post("/mappings/{mapping_id}/unlink", response_model=Envelope[EntityMappingOut])
def unlink_entity_mapping(
    mapping_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
) -> Envelope[EntityMappingOut]:
    row = get_owned(db, ExternalEntityMapping, ctx.tenant_id, mapping_id)
    unlink_mapping(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, mapping=row)
    db.commit()
    db.refresh(row)
    return Envelope(data=_mapping_out(row))


@router.post("/credentials", response_model=Envelope[IntegrationAccountOut])
def save_provider_credential(
    body: CredentialIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
) -> Envelope[IntegrationAccountOut]:
    allowed = {"linkedin", "meta", "twilio", "vapi", "apify", "exotel", "openai", "recall", "enrichment"}
    if body.provider not in allowed:
        raise HTTPException(status_code=422, detail="Provider is not in the tenant credential allow-list")
    row = upsert_token_account(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        provider=body.provider,
        access_token=body.access_token,
        account_key=body.account_key,
        extra=body.extra,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=IntegrationAccountOut.model_validate(public_account(row)))


@router.post("/provision-defaults", response_model=Envelope[dict])
def provision_defaults(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
) -> Envelope[dict]:
    provisioned = provision_env_credentials(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data={"provisioned": provisioned, "channels": channel_modes(db, ctx.tenant_id)})


@router.patch("/mappings/{mapping_id}", response_model=Envelope[EntityMappingOut])
def change_entity_mapping(
    mapping_id: UUID,
    body: EntityMappingChangeIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("integrations.write"))],
) -> Envelope[EntityMappingOut]:
    row = get_owned(db, ExternalEntityMapping, ctx.tenant_id, mapping_id)
    try:
        target_id = UUID(body.internal_entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="internal_entity_id must be a UUID") from exc
    if body.internal_entity_type == "customer":
        get_owned(db, Customer, ctx.tenant_id, target_id)
    confirm_mapping(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        mapping=row,
        internal_entity_type=body.internal_entity_type,
        internal_entity_id=body.internal_entity_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_mapping_out(row))


@router.post("/product-usage/events/{routing_token}")
async def product_usage_events(
    routing_token: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_webhook_signature: Annotated[str | None, Header()] = None,
):
    from app.api.v1.webhooks import _handle_inbound

    return await _handle_inbound("usage", request, db, routing_token, x_webhook_signature, None, None)

