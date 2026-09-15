import base64
import hashlib
import hmac
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.db.tenant_context import set_tenant_context
from app.models.identity import Tenant, User
from app.schemas.common import Envelope
from app.services.inbox import process_inbox_event, record_inbox_event
from app.services.webhook_routes import resolve_tenant_id

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_webhook_signature(*, body: bytes, signature: str | None) -> None:
    settings = get_settings()
    secret = settings.integrations_webhook_secret or settings.secret_key
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _verify_twilio(*, url: str, params: dict[str, str], signature: str | None, raw: bytes) -> None:
    settings = get_settings()
    if not settings.twilio_auth_token:
        verify_webhook_signature(body=raw, signature=signature)
        return
    if not signature:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    expected = hmac.new(settings.twilio_auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    digest = base64.b64encode(expected).decode()
    if not hmac.compare_digest(digest, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _verify_vapi(*, body: bytes, signature: str | None, vapi_secret: str | None) -> None:
    settings = get_settings()
    if settings.vapi_webhook_secret:
        if not vapi_secret or not hmac.compare_digest(settings.vapi_webhook_secret, vapi_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        return
    verify_webhook_signature(body=body, signature=signature)


def _enqueue_or_process(db: Session, event, *, actor_id: UUID) -> str:
    settings = get_settings()
    if settings.webhook_inline_process:
        return process_inbox_event(db, event, actor_id=actor_id)
    try:
        from app.workers.celery_app import process_inbox_event_task

        process_inbox_event_task.delay(str(event.id), str(event.tenant_id))
        return "queued"
    except Exception:  # noqa: BLE001
        return process_inbox_event(db, event, actor_id=actor_id)


async def _handle_inbound(
    provider: str,
    request: Request,
    db: Session,
    routing_token: str,
    x_webhook_signature: str | None,
    x_twilio_signature: str | None,
    x_vapi_secret: str | None,
) -> Envelope[dict]:
    settings = get_settings()
    raw = await request.body()
    if len(raw) > settings.webhook_max_body_bytes:
        raise HTTPException(status_code=413, detail="Payload too large")
    enforce_rate_limit(
        key=f"webhook:{provider}:{request.client.host if request.client else 'unknown'}",
        limit=120,
        window_seconds=60,
    )
    normalized = provider.strip().lower()
    if normalized == "exotel":
        allow = [item.strip() for item in settings.exotel_ip_allowlist.split(",") if item.strip()]
        client_ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (
            request.client.host if request.client else ""
        )
        if allow and client_ip not in allow:
            raise HTTPException(status_code=401, detail="Exotel callback IP is not allowlisted")
        form = dict(await request.form()) if "form" in request.headers.get("content-type", "") else {}
        if form:
            payload = {str(key): str(value) for key, value in form.items()}
        else:
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON") from exc
            payload = payload if isinstance(payload, dict) else {}
        # Exotel does not HMAC-sign callbacks. Auth is the secret routing token plus optional IP allowlist.
    elif normalized == "twilio":
        form = dict(await request.form()) if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded") else {}
        if form:
            payload = {str(key): str(value) for key, value in form.items()}
        else:
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON") from exc
            payload = payload if isinstance(payload, dict) else {}
        _verify_twilio(
            url=str(request.url),
            params={str(k): str(v) for k, v in payload.items()},
            signature=x_twilio_signature or x_webhook_signature,
            raw=raw,
        )
    elif normalized == "vapi":
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON")
        _verify_vapi(body=raw, signature=x_webhook_signature, vapi_secret=x_vapi_secret)
    else:
        verify_webhook_signature(body=raw, signature=x_webhook_signature)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON")
    if "tenant_id" in payload:
        payload = {key: value for key, value in payload.items() if key != "tenant_id"}
    tenant_id = resolve_tenant_id(db, provider=normalized, raw_token=routing_token)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Unknown webhook route")
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True)))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    set_tenant_context(db, tenant_id)
    actor = db.scalar(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)))
    if actor is None:
        raise HTTPException(status_code=409, detail="No active tenant user")
    external_id = str(
        payload.get("external_id")
        or payload.get("provider_message_id")
        or payload.get("CallSid")
        or payload.get("Sid")
        or payload.get("id")
        or ""
    )
    if not external_id:
        raise HTTPException(status_code=400, detail="external_id is required")
    event = record_inbox_event(
        db,
        tenant_id=tenant_id,
        actor_id=actor.id,
        provider=normalized,
        external_id=external_id,
        payload=payload,
    )
    db.commit()
    db.refresh(event)
    status = _enqueue_or_process(db, event, actor_id=actor.id)
    db.commit()
    return Envelope(data={"id": str(event.id), "status": status})


@router.post("/{provider}/{routing_token}")
async def inbound_webhook(
    provider: str,
    routing_token: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_webhook_signature: Annotated[str | None, Header()] = None,
    x_twilio_signature: Annotated[str | None, Header()] = None,
    x_vapi_secret: Annotated[str | None, Header()] = None,
) -> Envelope[dict]:
    return await _handle_inbound(
        provider,
        request,
        db,
        routing_token,
        x_webhook_signature,
        x_twilio_signature,
        x_vapi_secret,
    )
