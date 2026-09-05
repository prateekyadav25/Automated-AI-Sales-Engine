from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.logging import correlation_id_ctx, tenant_id_ctx
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.identity import User
from app.services.rbac import user_permissions

bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user: User
    tenant_id: UUID
    permissions: set[str]
    correlation_id: str


def get_correlation_id(x_correlation_id: Annotated[str | None, Header()] = None) -> str:
    value = x_correlation_id or "local"
    correlation_id_ctx.set(value)
    return value


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> AuthContext:
    _ = refresh_token
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(creds.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    user = db.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    tenant_id_ctx.set(str(user.tenant_id))
    return AuthContext(
        user=user,
        tenant_id=user.tenant_id,
        permissions=user_permissions(db, user),
        correlation_id=correlation_id,
    )


def require_permission(permission: str) -> Callable[[AuthContext], AuthContext]:
    def checker(ctx: Annotated[AuthContext, Depends(get_current_user)]) -> AuthContext:
        if permission not in ctx.permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return ctx

    return checker
