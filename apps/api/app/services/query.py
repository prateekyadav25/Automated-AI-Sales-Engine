from collections.abc import Sequence
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.base import TenantOwnedMixin


def not_deleted(model: type[TenantOwnedMixin]):
    return model.deleted_at.is_(None)


def get_owned(db: Session, model: type, tenant_id: UUID, entity_id: UUID):
    row = db.scalar(
        select(model).where(model.id == entity_id, model.tenant_id == tenant_id, model.deleted_at.is_(None))
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return row


def paginate(db: Session, stmt: Select[Any], page: int, page_size: int) -> tuple[Sequence[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return rows, int(total)
