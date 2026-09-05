from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import AuthContext, get_correlation_id, get_current_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse
from app.schemas.common import Envelope
from app.services import auth as auth_service
from app.services.auth import _to_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 86400,
        path="/api/v1/auth",
    )


@router.post("/login", response_model=Envelope[LoginResponse])
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
) -> Envelope[LoginResponse]:
    payload, raw = auth_service.login(
        db,
        body.email,
        body.password,
        request.client.host if request.client else None,
        correlation_id,
    )
    _set_refresh(response, raw)
    return Envelope(data=payload)


@router.post("/refresh", response_model=Envelope[LoginResponse])
def refresh(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> Envelope[LoginResponse]:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    payload, raw = auth_service.rotate_refresh(db, refresh_token)
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
