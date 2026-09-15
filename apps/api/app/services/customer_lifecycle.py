from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import Account, Customer, Opportunity
from app.models.identity import User
from app.services.rbac import user_permissions

CUSTOMER_STATES = [
    "NEW_CUSTOMER",
    "ONBOARDING",
    "IMPLEMENTING",
    "ADOPTING",
    "ACTIVE",
    "AT_RISK",
    "RENEWAL_UPCOMING",
    "RENEWAL_IN_PROGRESS",
    "RENEWED",
    "EXPANSION",
    "CHURNED",
]


def select_customer_owner(db: Session, *, tenant_id: UUID, opportunity: Opportunity | None, account: Account) -> User | None:
    if opportunity and opportunity.owner_id:
        owner = db.scalar(select(User).where(User.id == opportunity.owner_id, User.tenant_id == tenant_id, User.is_active.is_(True)))
        if owner is not None:
            return owner
    if account.created_by:
        owner = db.scalar(select(User).where(User.id == account.created_by, User.tenant_id == tenant_id, User.is_active.is_(True)))
        if owner is not None:
            return owner
    return None


def select_cs_owner(db: Session, *, tenant_id: UUID, account: Account) -> User | None:
    if account.created_by:
        owner = db.scalar(select(User).where(User.id == account.created_by, User.tenant_id == tenant_id, User.is_active.is_(True)))
        if owner is not None and "success.write" in user_permissions(db, owner):
            return owner
    users = db.scalars(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)).order_by(User.created_at.asc())).all()
    for user in users:
        if "success.write" in user_permissions(db, user):
            return user
    return None


def set_lifecycle(customer: Customer, state: str) -> None:
    if state not in CUSTOMER_STATES:
        return
    customer.lifecycle_state = state
    if state == "ONBOARDING" and customer.status == "onboarding":
        return
    if state in {"ONBOARDING", "IMPLEMENTING", "ADOPTING"}:
        customer.status = "onboarding"
    elif state == "CHURNED":
        customer.status = "churned"
    elif state in {"RENEWED", "EXPANSION", "ACTIVE"}:
        customer.status = "active"
    elif state in {"AT_RISK", "RENEWAL_UPCOMING", "RENEWAL_IN_PROGRESS"}:
        customer.status = "at_risk" if state == "AT_RISK" else customer.status


def mark_activated(customer: Customer) -> None:
    if customer.activated_at is None:
        customer.activated_at = datetime.now(UTC)
    if customer.lifecycle_state == "NEW_CUSTOMER":
        set_lifecycle(customer, "ONBOARDING")
