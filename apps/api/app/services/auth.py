from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models.identity import RefreshToken, User
from app.schemas.auth import LoginResponse, TokenUser
from app.services.audit import write_audit
from app.services.rbac import user_permissions, user_role_names


def _to_user(db: Session, user: User) -> TokenUser:
    return TokenUser(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        name=user.name,
        roles=user_role_names(db, user.id),
        permissions=sorted(user_permissions(db, user)),
        is_super_admin=user.is_super_admin,
    )


def login(db: Session, email: str, password: str, ip: str | None, correlation_id: str) -> tuple[LoginResponse, str]:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user.last_login_at = datetime.now(UTC)
    raw, hashed = new_refresh_token()
    settings = get_settings()
    db.add(
        RefreshToken(
            user_id=user.id,
            tenant_id=user.tenant_id,
            token_hash=hashed,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    write_audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=str(user.id),
        ip=ip,
        correlation_id=correlation_id,
    )
    db.commit()
    db.refresh(user)
    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id, email=user.email)
    return LoginResponse(access_token=token, user=_to_user(db, user)), raw


def rotate_refresh(db: Session, raw_token: str) -> tuple[LoginResponse, str]:
    hashed = hash_refresh_token(raw_token)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashed))
    if row is None or row.revoked_at is not None or row.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    row.revoked_at = datetime.now(UTC)
    raw, new_hash = new_refresh_token()
    settings = get_settings()
    db.add(
        RefreshToken(
            user_id=user.id,
            tenant_id=user.tenant_id,
            token_hash=new_hash,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    db.commit()
    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id, email=user.email)
    return LoginResponse(access_token=token, user=_to_user(db, user)), raw


def logout(db: Session, raw_token: str | None, user_id: UUID | None) -> None:
    if raw_token:
        row = db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        )
        if row is not None:
            row.revoked_at = datetime.now(UTC)
    db.commit()
    _ = user_id
