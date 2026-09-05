from uuid import UUID

from app.schemas.common import APIModel


class UserOut(APIModel):
    id: UUID
    email: str
    name: str
    is_active: bool
    is_super_admin: bool
    roles: list[str]


class TeamOut(APIModel):
    id: UUID
    name: str
    team_type: str


class TeamIn(APIModel):
    name: str
    team_type: str = "sales"


class TerritoryOut(APIModel):
    id: UUID
    name: str
    region: str


class TerritoryIn(APIModel):
    name: str
    region: str = ""


class FlagOut(APIModel):
    id: UUID
    key: str
    enabled: bool
    description: str


class FlagUpdate(APIModel):
    enabled: bool


class AuditOut(APIModel):
    id: UUID
    action: str
    entity_type: str
    entity_id: str
    actor_type: str
    created_at: str


class RoleOut(APIModel):
    id: UUID
    name: str
    description: str
    permissions: list[str]
