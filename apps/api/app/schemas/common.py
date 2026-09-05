from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Meta(BaseModel):
    page: int = 1
    page_size: int = 25
    total: int = 0


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class Envelope(BaseModel, Generic[T]):
    data: T | None = None
    meta: Meta | None = None
    error: ErrorBody | None = None


class PageQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)
    q: str = ""
