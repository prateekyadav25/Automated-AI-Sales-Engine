from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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
from app.db.tenant_context import (
    clear_lookup_context,
    set_login_email,
    set_refresh_token_hash,
    set_tenant_context,
)
from app.models.identity import RefreshToken, Tenant, User
from app.schemas.auth import LoginResponse, SessionOut, TokenUser
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


def _issue_refresh(db: Session, user: User, *, family_id: UUID | None = None) -> tuple[str, RefreshToken]:
    raw, hashed = new_refresh_token()
    settings = get_settings()
    now = datetime.now(UTC)
    row = RefreshToken(
        user_id=user.id,
        tenant_id=user.tenant_id,
        token_family_id=family_id or uuid4(),
        token_hash=hashed,
        jti_hash=hash_refresh_token(str(uuid4())),
        issued_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
    )
    db.add(row)
    db.flush()
    return raw, row


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _revoke_family(db: Session, family_id: UUID, *, reuse: bool = False) -> None:
    now = datetime.now(UTC)
    rows = db.scalars(select(RefreshToken).where(RefreshToken.token_family_id == family_id)).all()
    for row in rows:
        row.revoked_at = row.revoked_at or now
        if reuse:
            row.reuse_detected_at = row.reuse_detected_at or now


def login(
    db: Session,
    email: str,
    password: str,
    ip: str | None,
    correlation_id: str,
    tenant_slug: str | None = None,
) -> tuple[LoginResponse, str]:
    normalized = email.lower().strip()
    set_login_email(db, normalized)
    stmt = select(User).where(User.email == normalized)
    if tenant_slug:
        stmt = stmt.join(Tenant).where(Tenant.slug == tenant_slug)
    users = list(db.scalars(stmt).all())
    user = users[0] if len(users) == 1 else None
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        write_audit(
            db,
            tenant_id=user.tenant_id if user is not None else None,
            actor_id=user.id if user is not None else None,
            action="auth.login_failed",
            entity_type="user",
            entity_id=str(user.id) if user is not None else "",
            ip=ip,
            correlation_id=correlation_id,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    set_tenant_context(db, user.tenant_id)
    clear_lookup_context(db)
    user.last_login_at = datetime.now(UTC)
    raw, _row = _issue_refresh(db, user)
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


def rotate_refresh(db: Session, raw_token: str, ip: str | None = None, correlation_id: str = "") -> tuple[LoginResponse, str]:
    hashed = hash_refresh_token(raw_token)
    set_refresh_token_hash(db, hashed)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashed))
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    set_tenant_context(db, row.tenant_id)
    if row.revoked_at is not None or row.rotated_at is not None:
        _revoke_family(db, row.token_family_id, reuse=True)
        write_audit(
            db,
            tenant_id=row.tenant_id,
            actor_id=row.user_id,
            action="auth.refresh_reuse_detected",
            entity_type="refresh_token_family",
            entity_id=str(row.token_family_id),
            ip=ip,
            correlation_id=correlation_id,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if _aware(row.expires_at) < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    now = datetime.now(UTC)
    raw, new_row = _issue_refresh(db, user, family_id=row.token_family_id)
    row.revoked_at = now
    row.rotated_at = now
    row.replaced_by = new_row.id
    clear_lookup_context(db)
    db.commit()
    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id, email=user.email)
    return LoginResponse(access_token=token, user=_to_user(db, user)), raw


def logout(db: Session, raw_token: str | None, user_id: UUID | None) -> None:
    if raw_token:
        hashed = hash_refresh_token(raw_token)
        set_refresh_token_hash(db, hashed)
        row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hashed))
        if row is not None:
            set_tenant_context(db, row.tenant_id)
            write_audit(
                db,
                tenant_id=row.tenant_id,
                actor_id=row.user_id,
                action="auth.logout",
                entity_type="user",
                entity_id=str(row.user_id),
            )
            row.revoked_at = datetime.now(UTC)
    db.commit()
    _ = user_id


def list_sessions(db: Session, *, user_id: UUID, tenant_id: UUID) -> list[SessionOut]:
    set_tenant_context(db, tenant_id)
    rows = db.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.tenant_id == tenant_id)
        .order_by(RefreshToken.issued_at.desc())
    ).all()
    seen: set[UUID] = set()
    sessions: list[SessionOut] = []
    for row in rows:
        if row.token_family_id in seen:
            continue
        seen.add(row.token_family_id)
        active = row.revoked_at is None and _aware(row.expires_at) >= datetime.now(UTC) and row.rotated_at is None
        latest = row
        for other in rows:
            if other.token_family_id == row.token_family_id and other.issued_at >= latest.issued_at:
                latest = other
                active = latest.revoked_at is None and _aware(latest.expires_at) >= datetime.now(UTC) and latest.rotated_at is None
        sessions.append(
            SessionOut(
                family_id=row.token_family_id,
                issued_at=latest.issued_at,
                expires_at=latest.expires_at,
                revoked=not active,
                current=active,
            )
        )
    return sessions


def revoke_session(db: Session, *, user_id: UUID, tenant_id: UUID, family_id: UUID) -> None:
    set_tenant_context(db, tenant_id)
    row = db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_family_id == family_id,
            RefreshToken.user_id == user_id,
            RefreshToken.tenant_id == tenant_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    _revoke_family(db, family_id)
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="auth.session_revoked",
        entity_type="refresh_token_family",
        entity_id=str(family_id),
    )
    db.commit()


def revoke_all_sessions(db: Session, *, user_id: UUID, tenant_id: UUID) -> None:
    set_tenant_context(db, tenant_id)
    rows = db.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.tenant_id == tenant_id)
    ).all()
    families = {row.token_family_id for row in rows}
    for family_id in families:
        _revoke_family(db, family_id)
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="auth.sessions_revoked",
        entity_type="user",
        entity_id=str(user_id),
    )
    db.commit()
