from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.crm import Account
from app.models.market import (
    AccountSignal,
    CompetitiveSignal,
    IntentSignal,
    Market,
    MarketSignal,
    TechnologySignal,
    TriggerEvent,
)
from app.schemas.common import Envelope, Meta
from app.schemas.market import MarketIn, MarketOut, MarketOverview, RefreshOut, SignalOut, TriggerOut
from app.services.audit import emit_event, write_audit
from app.services.market import refresh_account_intelligence, score_market
from app.services.query import get_owned, paginate

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview", response_model=Envelope[MarketOverview])
def overview(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("markets.read"))],
) -> Envelope[MarketOverview]:
    markets = db.scalar(select(func.count()).where(Market.tenant_id == ctx.tenant_id, Market.deleted_at.is_(None))) or 0
    scored = (
        db.scalar(
            select(func.count()).where(
                Market.tenant_id == ctx.tenant_id, Market.deleted_at.is_(None), Market.attractiveness > 0
            )
        )
        or 0
    )
    signals = (
        (db.scalar(select(func.count()).where(MarketSignal.tenant_id == ctx.tenant_id, MarketSignal.deleted_at.is_(None))) or 0)
        + (db.scalar(select(func.count()).where(AccountSignal.tenant_id == ctx.tenant_id, AccountSignal.deleted_at.is_(None))) or 0)
        + (db.scalar(select(func.count()).where(IntentSignal.tenant_id == ctx.tenant_id, IntentSignal.deleted_at.is_(None))) or 0)
        + (db.scalar(select(func.count()).where(TechnologySignal.tenant_id == ctx.tenant_id, TechnologySignal.deleted_at.is_(None))) or 0)
        + (db.scalar(select(func.count()).where(CompetitiveSignal.tenant_id == ctx.tenant_id, CompetitiveSignal.deleted_at.is_(None))) or 0)
    )
    mock_signals = (
        db.scalar(select(func.count()).where(AccountSignal.tenant_id == ctx.tenant_id, AccountSignal.is_mock.is_(True))) or 0
    ) + (db.scalar(select(func.count()).where(IntentSignal.tenant_id == ctx.tenant_id, IntentSignal.is_mock.is_(True))) or 0)
    triggers = db.scalar(select(func.count()).where(TriggerEvent.tenant_id == ctx.tenant_id, TriggerEvent.deleted_at.is_(None))) or 0
    return Envelope(
        data=MarketOverview(
            markets=int(markets),
            signals=int(signals),
            triggers=int(triggers),
            mock_signals=int(mock_signals),
            scored_markets=int(scored),
        )
    )


@router.get("", response_model=Envelope[list[MarketOut]])
def list_markets(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("markets.read"))],
    page: int = 1,
    page_size: int = 25,
    q: str = "",
) -> Envelope[list[MarketOut]]:
    stmt = select(Market).where(Market.tenant_id == ctx.tenant_id, Market.deleted_at.is_(None))
    if q:
        stmt = stmt.where(or_(Market.name.ilike(f"%{q}%"), Market.industry.ilike(f"%{q}%")))
    rows, total = paginate(db, stmt.order_by(Market.created_at.desc()), page, page_size)
    return Envelope(data=[MarketOut.model_validate(row) for row in rows], meta=Meta(page=page, page_size=page_size, total=total))


@router.post("", response_model=Envelope[MarketOut])
def create_market(
    body: MarketIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("markets.write"))],
) -> Envelope[MarketOut]:
    row = Market(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    db.flush()
    score_market(db, row)
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="market.create",
        entity_type="market",
        entity_id=str(row.id),
        after=body.model_dump(),
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=MarketOut.model_validate(row))


@router.get("/{market_id}", response_model=Envelope[MarketOut])
def get_market(
    market_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("markets.read"))],
) -> Envelope[MarketOut]:
    return Envelope(data=MarketOut.model_validate(get_owned(db, Market, ctx.tenant_id, market_id)))


@router.post("/{market_id}/score", response_model=Envelope[MarketOut])
def rescore_market(
    market_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("markets.write"))],
) -> Envelope[MarketOut]:
    row = get_owned(db, Market, ctx.tenant_id, market_id)
    score_market(db, row)
    emit_event(
        db,
        tenant_id=ctx.tenant_id,
        event_type="market.scored",
        entity_type="market",
        entity_id=str(row.id),
        payload={"attractiveness": row.attractiveness},
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=MarketOut.model_validate(row))


@router.get("/desk/signals", response_model=Envelope[list[SignalOut]])
def list_signals(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("signals.read"))],
    kind: str = "",
    page: int = 1,
    page_size: int = 40,
) -> Envelope[list[SignalOut]]:
    items: list[SignalOut] = []
    if kind in {"", "market"}:
        for row in db.scalars(select(MarketSignal).where(MarketSignal.tenant_id == ctx.tenant_id, MarketSignal.deleted_at.is_(None)).order_by(MarketSignal.created_at.desc()).limit(40)):
            items.append(
                SignalOut(
                    id=row.id,
                    kind="market",
                    title=row.title,
                    source=row.source,
                    evidence=row.evidence,
                    confidence=row.confidence,
                    impact=row.impact,
                    recommended_action=row.recommended_action,
                    occurred_at=row.occurred_at,
                    is_mock=row.is_mock,
                    market_id=row.market_id,
                )
            )
    if kind in {"", "account"}:
        for row in db.scalars(select(AccountSignal).where(AccountSignal.tenant_id == ctx.tenant_id, AccountSignal.deleted_at.is_(None)).order_by(AccountSignal.created_at.desc()).limit(40)):
            items.append(
                SignalOut(
                    id=row.id,
                    kind="account",
                    title=row.title,
                    source=row.source,
                    evidence=row.evidence,
                    confidence=row.confidence,
                    impact=row.impact,
                    recommended_action=row.recommended_action,
                    occurred_at=row.occurred_at,
                    is_mock=row.is_mock,
                    account_id=row.account_id,
                )
            )
    if kind in {"", "intent"}:
        for row in db.scalars(select(IntentSignal).where(IntentSignal.tenant_id == ctx.tenant_id, IntentSignal.deleted_at.is_(None)).order_by(IntentSignal.created_at.desc()).limit(40)):
            items.append(
                SignalOut(
                    id=row.id,
                    kind="intent",
                    title=row.topic,
                    source=row.source,
                    evidence=row.evidence,
                    confidence=row.confidence,
                    impact=row.impact,
                    recommended_action=row.recommended_action,
                    occurred_at=row.occurred_at,
                    is_mock=row.is_mock,
                    account_id=row.account_id,
                    extra={"intensity": row.intensity},
                )
            )
    if kind in {"", "technology"}:
        for row in db.scalars(select(TechnologySignal).where(TechnologySignal.tenant_id == ctx.tenant_id, TechnologySignal.deleted_at.is_(None)).order_by(TechnologySignal.created_at.desc()).limit(40)):
            items.append(
                SignalOut(
                    id=row.id,
                    kind="technology",
                    title=row.technology,
                    source=row.source,
                    evidence=row.evidence,
                    confidence=row.confidence,
                    impact=row.impact,
                    recommended_action=row.recommended_action,
                    occurred_at=row.occurred_at,
                    is_mock=row.is_mock,
                    account_id=row.account_id,
                    extra={"category": row.category},
                )
            )
    if kind in {"", "competitive"}:
        for row in db.scalars(select(CompetitiveSignal).where(CompetitiveSignal.tenant_id == ctx.tenant_id, CompetitiveSignal.deleted_at.is_(None)).order_by(CompetitiveSignal.created_at.desc()).limit(40)):
            items.append(
                SignalOut(
                    id=row.id,
                    kind="competitive",
                    title=row.competitor,
                    source=row.source,
                    evidence=row.evidence,
                    confidence=row.confidence,
                    impact=row.impact,
                    recommended_action=row.recommended_action,
                    occurred_at=row.occurred_at,
                    is_mock=row.is_mock,
                    account_id=row.account_id,
                    extra={"movement": row.movement},
                )
            )
    items.sort(key=lambda row: row.occurred_at or row.id.hex, reverse=True)
    start = (page - 1) * page_size
    slice_rows = items[start : start + page_size]
    return Envelope(data=slice_rows, meta=Meta(page=page, page_size=page_size, total=len(items)))


@router.get("/desk/triggers", response_model=Envelope[list[TriggerOut]])
def list_triggers(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("signals.read"))],
    page: int = 1,
    page_size: int = 25,
) -> Envelope[list[TriggerOut]]:
    stmt = select(TriggerEvent).where(TriggerEvent.tenant_id == ctx.tenant_id, TriggerEvent.deleted_at.is_(None)).order_by(TriggerEvent.created_at.desc())
    rows, total = paginate(db, stmt, page, page_size)
    return Envelope(data=[TriggerOut.model_validate(row) for row in rows], meta=Meta(page=page, page_size=page_size, total=total))


@router.post("/refresh", response_model=Envelope[RefreshOut])
def refresh_signals(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("signals.write"))],
) -> Envelope[RefreshOut]:
    accounts = db.scalars(
        select(Account).where(Account.tenant_id == ctx.tenant_id, Account.deleted_at.is_(None)).limit(20)
    ).all()
    created = {"account_signals": 0, "intent_signals": 0, "technology_signals": 0, "triggers": 0}
    for account in accounts:
        result = refresh_account_intelligence(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, account=account)
        for key, value in result.items():
            created[key] = created.get(key, 0) + value
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="market.refresh",
        entity_type="signal",
        after=created,
        correlation_id=ctx.correlation_id,
        actor_type="human",
    )
    db.commit()
    return Envelope(data=RefreshOut(accounts_scanned=len(accounts), created=created, provider="mock-intelligence", is_mock=True))
