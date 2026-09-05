from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class LoginRequest(APIModel):
    email: str
    password: str = Field(min_length=8)


class TokenUser(APIModel):
    id: UUID
    tenant_id: UUID
    email: str
    name: str
    roles: list[str]
    permissions: list[str]
    is_super_admin: bool


class LoginResponse(APIModel):
    access_token: str
    token_type: str = "bearer"
    user: TokenUser
