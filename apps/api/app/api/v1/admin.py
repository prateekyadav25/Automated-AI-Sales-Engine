from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.identity import AuditLog, FeatureFlag, Role, Team, Territory, User, UserRole
from app.schemas.admin import (
    AuditOut,
    FlagOut,
    FlagUpdate,
    RoleOut,
    TeamIn,
    TeamOut,
    TerritoryIn,
    TerritoryOut,
    UserOut,
)
from app.schemas.common import Envelope, Meta
from app.services.audit import write_audit
from app.services.rbac import user_role_names

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=Envelope[list[UserOut]])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("users.read"))],
) -> Envelope[list[UserOut]]:
    rows = db.scalars(select(User).where(User.tenant_id == ctx.tenant_id)).all()
    data = [
        UserOut(
            id=row.id,
            email=row.email,
            name=row.name,
            is_active=row.is_active,
            is_super_admin=row.is_super_admin,
            roles=user_role_names(db, row.id),
        )
        for row in rows
    ]
    return Envelope(data=data, meta=Meta(total=len(data), page_size=len(data) or 25))


@router.get("/roles", response_model=Envelope[list[RoleOut]])
def list_roles(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("roles.read"))],
) -> Envelope[list[RoleOut]]:
    from app.models.identity import Permission, RolePermission

    rows = db.scalars(select(Role).where(Role.tenant_id == ctx.tenant_id)).all()
    data = []
    for role in rows:
        keys = db.scalars(
            select(Permission.key)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        ).all()
        data.append(
            RoleOut(id=role.id, name=role.name, description=role.description, permissions=list(keys))
        )
    return Envelope(data=data, meta=Meta(total=len(data)))


@router.get("/teams", response_model=Envelope[list[TeamOut]])
def list_teams(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("teams.read"))],
) -> Envelope[list[TeamOut]]:
    rows = db.scalars(select(Team).where(Team.tenant_id == ctx.tenant_id)).all()
    return Envelope(data=[TeamOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/teams", response_model=Envelope[TeamOut])
def create_team(
    body: TeamIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("teams.write"))],
) -> Envelope[TeamOut]:
    row = Team(tenant_id=ctx.tenant_id, name=body.name, team_type=body.team_type)
    db.add(row)
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="team.create",
        entity_type="team",
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=TeamOut.model_validate(row))


@router.get("/territories", response_model=Envelope[list[TerritoryOut]])
def list_territories(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("teams.read"))],
) -> Envelope[list[TerritoryOut]]:
    rows = db.scalars(select(Territory).where(Territory.tenant_id == ctx.tenant_id)).all()
    return Envelope(data=[TerritoryOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/territories", response_model=Envelope[TerritoryOut])
def create_territory(
    body: TerritoryIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("teams.write"))],
) -> Envelope[TerritoryOut]:
    row = Territory(tenant_id=ctx.tenant_id, name=body.name, region=body.region)
    db.add(row)
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="territory.create",
        entity_type="territory",
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=TerritoryOut.model_validate(row))


@router.get("/flags", response_model=Envelope[list[FlagOut]])
def list_flags(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("flags.read"))],
) -> Envelope[list[FlagOut]]:
    rows = db.scalars(select(FeatureFlag).where(FeatureFlag.tenant_id == ctx.tenant_id)).all()
    return Envelope(data=[FlagOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.patch("/flags/{flag_id}", response_model=Envelope[FlagOut])
def update_flag(
    flag_id: str,
    body: FlagUpdate,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("flags.write"))],
) -> Envelope[FlagOut]:
    from uuid import UUID

    row = db.scalar(
        select(FeatureFlag).where(FeatureFlag.id == UUID(flag_id), FeatureFlag.tenant_id == ctx.tenant_id)
    )
    from fastapi import HTTPException

    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    row.enabled = body.enabled
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="flag.update",
        entity_type="feature_flag",
        entity_id=flag_id,
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=FlagOut.model_validate(row))


@router.get("/audit", response_model=Envelope[list[AuditOut]])
def list_audit(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("audit.read"))],
) -> Envelope[list[AuditOut]]:
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.tenant_id == ctx.tenant_id)
        .order_by(AuditLog.created_at.desc())
        .limit(100)
    ).all()
    data = [
        AuditOut(
            id=row.id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            actor_type=row.actor_type,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]
    return Envelope(data=data, meta=Meta(total=len(data)))


@router.get("/role-assignments")
def role_assignments(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("users.read"))],
) -> Envelope[list[dict]]:
    rows = db.scalars(select(UserRole).join(User).where(User.tenant_id == ctx.tenant_id)).all()
    return Envelope(data=[{"user_id": str(r.user_id), "role_id": str(r.role_id)} for r in rows])
