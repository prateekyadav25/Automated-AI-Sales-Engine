from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import AuthContext, get_correlation_id, get_current_user
from app.core.rate_limit import enforce_rate_limit
from app.core.security import create_access_token
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse, SessionOut
from app.schemas.common import Envelope
from app.services import auth as auth_service
from app.services.auth import _to_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_refresh(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=raw,
        httponly=True,
        secure=settings.cookie_secure or settings.is_production,
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 86400,
        path="/api/v1/auth",
        domain=settings.cookie_domain or None,
    )


def _assert_refresh_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    if origin not in get_settings().cors_origin_list:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid origin")


@router.post("/login", response_model=Envelope[LoginResponse])
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
) -> Envelope[LoginResponse]:
    settings = get_settings()
    enforce_rate_limit(
        key=f"login:{_client_ip(request)}:{body.email.lower()}",
        limit=settings.auth_login_limit,
        window_seconds=settings.auth_rate_window_seconds,
        fail_closed=True,
    )
    payload, raw = auth_service.login(
        db,
        body.email,
        body.password,
        _client_ip(request),
        correlation_id,
        tenant_slug=body.tenant,
    )
    _set_refresh(response, raw)
    return Envelope(data=payload)


@router.post("/refresh", response_model=Envelope[LoginResponse])
def refresh(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> Envelope[LoginResponse]:
    settings = get_settings()
    _assert_refresh_origin(request)
    enforce_rate_limit(
        key=f"refresh:{_client_ip(request)}",
        limit=settings.auth_refresh_limit,
        window_seconds=settings.auth_rate_window_seconds,
        fail_closed=True,
    )
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    payload, raw = auth_service.rotate_refresh(db, refresh_token, _client_ip(request), correlation_id)
    _set_refresh(response, raw)
    return Envelope(data=payload)


@router.post("/logout")
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> Envelope[dict]:
    auth_service.logout(db, refresh_token, None)
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    return Envelope(data={"ok": True})


@router.get("/me", response_model=Envelope[LoginResponse])
def me(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(get_current_user)],
) -> Envelope[LoginResponse]:
    token = create_access_token(user_id=ctx.user.id, tenant_id=ctx.tenant_id, email=ctx.user.email)
    return Envelope(data=LoginResponse(access_token=token, user=_to_user(db, ctx.user)))


@router.get("/sessions", response_model=Envelope[list[SessionOut]])
def sessions(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(get_current_user)],
) -> Envelope[list[SessionOut]]:
    return Envelope(data=auth_service.list_sessions(db, user_id=ctx.user.id, tenant_id=ctx.tenant_id))


@router.post("/sessions/{family_id}/revoke", response_model=Envelope[dict])
def revoke_session(
    family_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(get_current_user)],
) -> Envelope[dict]:
    auth_service.revoke_session(db, user_id=ctx.user.id, tenant_id=ctx.tenant_id, family_id=family_id)
    return Envelope(data={"ok": True})


@router.post("/sessions/revoke-all", response_model=Envelope[dict])
def revoke_all_sessions(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(get_current_user)],
) -> Envelope[dict]:
    auth_service.revoke_all_sessions(db, user_id=ctx.user.id, tenant_id=ctx.tenant_id)
    return Envelope(data={"ok": True})
