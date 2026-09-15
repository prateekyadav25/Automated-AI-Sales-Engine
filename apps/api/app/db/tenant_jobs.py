from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tenant_context import clear_tenant_context, set_tenant_context
from app.models.identity import Tenant

Callback = Callable[[UUID], int | None]


def run_per_tenant(db: Session, callback: Callback) -> int:
    clear_tenant_context(db)
    tenant_ids = list(db.scalars(select(Tenant.id).where(Tenant.is_active.is_(True))).all())
    total = 0
    for tenant_id in tenant_ids:
        set_tenant_context(db, tenant_id)
        total += callback(tenant_id) or 0
    clear_tenant_context(db)
    return total
