from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, get_current_user
from app.db.session import get_db
from app.models.crm import Account, Contact, Lead, Opportunity, Task
from app.models.lifecycle import Campaign, Product, Sequence
from app.models.market import Market
from app.schemas.common import Envelope
from app.schemas.crm import SearchHit, SearchOut

router = APIRouter(tags=["search"])


@router.get("/search", response_model=Envelope[SearchOut])
def global_search(
    q: str,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(get_current_user)],
) -> Envelope[SearchOut]:
    term = q.strip()
    hits: list[SearchHit] = []
    if len(term) < 2:
        return Envelope(data=SearchOut(hits=[]))
    like = f"%{term}%"
    if "accounts.read" in ctx.permissions:
        for row in db.scalars(
            select(Account)
            .where(
                Account.tenant_id == ctx.tenant_id,
                Account.deleted_at.is_(None),
                or_(Account.name.ilike(like), Account.industry.ilike(like)),
            )
            .limit(5)
        ):
            hits.append(SearchHit(entity_type="account", id=row.id, title=row.name, subtitle=row.industry))
    if "leads.read" in ctx.permissions:
        for row in db.scalars(
            select(Lead)
            .where(
                Lead.tenant_id == ctx.tenant_id,
                Lead.deleted_at.is_(None),
                or_(Lead.first_name.ilike(like), Lead.last_name.ilike(like), Lead.company_name.ilike(like)),
            )
            .limit(5)
        ):
            hits.append(
                SearchHit(
                    entity_type="lead",
                    id=row.id,
                    title=f"{row.first_name} {row.last_name}",
                    subtitle=row.company_name,
                )
            )
    if "contacts.read" in ctx.permissions:
        for row in db.scalars(
            select(Contact)
            .where(
                Contact.tenant_id == ctx.tenant_id,
                Contact.deleted_at.is_(None),
                or_(Contact.first_name.ilike(like), Contact.last_name.ilike(like), Contact.email.ilike(like)),
            )
            .limit(5)
        ):
            hits.append(
                SearchHit(
                    entity_type="contact",
                    id=row.id,
                    title=f"{row.first_name} {row.last_name}",
                    subtitle=row.title,
                )
            )
    if "opportunities.read" in ctx.permissions:
        for row in db.scalars(
            select(Opportunity)
            .where(
                Opportunity.tenant_id == ctx.tenant_id,
                Opportunity.deleted_at.is_(None),
                Opportunity.name.ilike(like),
            )
            .limit(5)
        ):
            hits.append(SearchHit(entity_type="opportunity", id=row.id, title=row.name, subtitle=row.stage))
    if "markets.read" in ctx.permissions:
        for row in db.scalars(
            select(Market)
            .where(
                Market.tenant_id == ctx.tenant_id,
                Market.deleted_at.is_(None),
                or_(Market.name.ilike(like), Market.industry.ilike(like)),
            )
            .limit(5)
        ):
            hits.append(SearchHit(entity_type="market", id=row.id, title=row.name, subtitle=row.industry))
    if "campaigns.read" in ctx.permissions:
        for row in db.scalars(
            select(Campaign)
            .where(Campaign.tenant_id == ctx.tenant_id, Campaign.deleted_at.is_(None), Campaign.name.ilike(like))
            .limit(5)
        ):
            hits.append(SearchHit(entity_type="campaign", id=row.id, title=row.name, subtitle=row.channel))
    if "sequences.read" in ctx.permissions:
        for row in db.scalars(
            select(Sequence)
            .where(Sequence.tenant_id == ctx.tenant_id, Sequence.deleted_at.is_(None), Sequence.name.ilike(like))
            .limit(5)
        ):
            hits.append(SearchHit(entity_type="sequence", id=row.id, title=row.name, subtitle=row.channel))
    if "commercial.read" in ctx.permissions:
        for row in db.scalars(
            select(Product)
            .where(Product.tenant_id == ctx.tenant_id, Product.deleted_at.is_(None), Product.name.ilike(like))
            .limit(5)
        ):
            hits.append(SearchHit(entity_type="product", id=row.id, title=row.name, subtitle=row.sku))
    if "tasks.read" in ctx.permissions:
        for row in db.scalars(
            select(Task)
            .where(Task.tenant_id == ctx.tenant_id, Task.deleted_at.is_(None), Task.title.ilike(like))
            .limit(5)
        ):
            hits.append(SearchHit(entity_type="task", id=row.id, title=row.title, subtitle=row.status))
    return Envelope(data=SearchOut(hits=hits))
