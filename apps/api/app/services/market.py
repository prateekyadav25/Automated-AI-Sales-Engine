from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm import ICP, Account
from app.models.market import (
    AccountSignal,
    CompetitiveSignal,
    IntentSignal,
    Market,
    MarketSignal,
    TechnologySignal,
    TriggerEvent,
)
from app.providers.intelligence import (
    get_company_provider,
    get_intent_provider,
    get_news_provider,
    get_technology_provider,
)


def clamp(value: int) -> int:
    return max(0, min(100, value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _default_icp(db: Session, tenant_id: UUID) -> ICP | None:
    rows = db.scalars(select(ICP).where(ICP.tenant_id == tenant_id, ICP.deleted_at.is_(None))).all()
    return next((row for row in rows if row.is_default), rows[0] if rows else None)


def score_market(db: Session, market: Market) -> Market:
    icp = _default_icp(db, market.tenant_id)
    industry = market.industry.lower()
    icp_hit = bool(icp and industry and industry in icp.industries.lower())
    geo_hit = bool(icp and market.geography and market.geography.lower() in icp.geographies.lower())

    market_signals = db.scalars(
        select(MarketSignal).where(
            MarketSignal.tenant_id == market.tenant_id,
            MarketSignal.market_id == market.id,
            MarketSignal.deleted_at.is_(None),
        )
    ).all()
    accounts = db.scalars(
        select(Account).where(
            Account.tenant_id == market.tenant_id,
            Account.deleted_at.is_(None),
            Account.industry == market.industry,
        )
    ).all()
    account_ids = [row.id for row in accounts]
    account_signals = []
    intent = []
    tech = []
    competitive = []
    triggers = []
    if account_ids:
        account_signals = db.scalars(
            select(AccountSignal).where(
                AccountSignal.tenant_id == market.tenant_id,
                AccountSignal.account_id.in_(account_ids),
                AccountSignal.deleted_at.is_(None),
            )
        ).all()
        intent = db.scalars(
            select(IntentSignal).where(
                IntentSignal.tenant_id == market.tenant_id,
                IntentSignal.account_id.in_(account_ids),
                IntentSignal.deleted_at.is_(None),
            )
        ).all()
        tech = db.scalars(
            select(TechnologySignal).where(
                TechnologySignal.tenant_id == market.tenant_id,
                TechnologySignal.account_id.in_(account_ids),
                TechnologySignal.deleted_at.is_(None),
            )
        ).all()
        competitive = db.scalars(
            select(CompetitiveSignal).where(
                CompetitiveSignal.tenant_id == market.tenant_id,
                CompetitiveSignal.account_id.in_(account_ids),
                CompetitiveSignal.deleted_at.is_(None),
            )
        ).all()
        triggers = db.scalars(
            select(TriggerEvent).where(
                TriggerEvent.tenant_id == market.tenant_id,
                TriggerEvent.account_id.in_(account_ids),
                TriggerEvent.deleted_at.is_(None),
            )
        ).all()

    signal_count = len(market_signals) + len(account_signals) + len(intent)
    confidences = [row.confidence for row in [*market_signals, *account_signals, *intent] if row.confidence]
    avg_conf = sum(confidences) // len(confidences) if confidences else 0
    high_impact = sum(1 for row in [*market_signals, *account_signals] if row.impact == "high")
    revenues = [int(row.annual_revenue) for row in accounts if row.annual_revenue]
    employees = [row.employee_count or 0 for row in accounts]
    recent_cutoff = datetime.now(UTC) - timedelta(days=90)
    recent_triggers = [row for row in triggers if row.occurred_at and _as_utc(row.occurred_at) >= recent_cutoff]
    ai_tech = [row for row in tech if "ai" in f"{row.technology} {row.category}".lower()]
    rfp_triggers = [row for row in triggers if row.trigger_type in {"rfp", "budget", "hiring", "procurement"}]

    market.attractiveness = clamp(
        (22 if icp_hit else 6)
        + (8 if geo_hit else 0)
        + min(25, signal_count * 4)
        + min(15, avg_conf // 7)
        + min(15, high_impact * 5)
        + min(15, len(accounts) * 3)
    )
    market.ai_readiness = clamp(8 + min(40, len(ai_tech) * 12) + min(30, len(intent) * 8) + (12 if industry in {"technology", "bfsi"} else 0))
    market.technology_readiness = clamp(10 + min(60, len(tech) * 15) + min(20, len(accounts)))
    market.budget_potential = clamp(
        8
        + min(40, (max(revenues) // 50_000_000) * 8 if revenues else 0)
        + min(30, (max(employees) // 1000) * 4 if employees else 0)
        + (10 if icp_hit else 0)
    )
    market.growth_potential = clamp(10 + min(40, len(intent) * 10) + min(30, len(recent_triggers) * 8) + min(20, high_impact * 6))
    market.competitive_intensity = clamp(5 + min(80, len(competitive) * 18))
    market.procurement_probability = clamp(6 + min(50, len(rfp_triggers) * 12) + min(25, avg_conf // 4) + (10 if icp_hit else 0))
    market.buying_timing = clamp(5 + min(70, len(recent_triggers) * 18) + min(25, len(intent) * 5))
    market.score_reasons = (
        f"ICP industry {'hit' if icp_hit else 'miss'}; {signal_count} signals; "
        f"{len(triggers)} triggers; {len(accounts)} mapped accounts; rules-v1."
    )
    market.score_version = "rules-v1"
    return market


def refresh_account_intelligence(db: Session, *, tenant_id: UUID, actor_id: UUID, account: Account) -> dict[str, int]:
    created = {"account_signals": 0, "intent_signals": 0, "technology_signals": 0, "triggers": 0}
    company = get_company_provider().lookup(name=account.name, domain=account.domain, industry=account.industry)
    news = get_news_provider().headlines(company_name=account.name, industry=account.industry)
    intent = get_intent_provider().topics(company_name=account.name, industry=account.industry)
    stack = get_technology_provider().stack(company_name=account.name, industry=account.industry)

    title = f"Firmographic refresh · {company.provider}"
    if db.scalar(select(AccountSignal.id).where(AccountSignal.tenant_id == tenant_id, AccountSignal.account_id == account.id, AccountSignal.title == title)) is None:
        db.add(
            AccountSignal(
                tenant_id=tenant_id,
                created_by=actor_id,
                account_id=account.id,
                signal_type="firmographic",
                title=title,
                source=company.provider,
                evidence=company.summary,
                confidence=55,
                impact="medium",
                recommended_action="Review account 360 against this mock card.",
                occurred_at=datetime.now(UTC),
                is_mock=company.is_mock,
            )
        )
        created["account_signals"] += 1

    for item in news:
        if db.scalar(select(TriggerEvent.id).where(TriggerEvent.tenant_id == tenant_id, TriggerEvent.account_id == account.id, TriggerEvent.title == item.title)) is None:
            db.add(
                TriggerEvent(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    account_id=account.id,
                    trigger_type="news",
                    title=item.title,
                    body=item.summary,
                    source=item.provider,
                    evidence=item.summary,
                    confidence=50,
                    impact="medium",
                    recommended_action="Confirm with the champion before treating as a live trigger.",
                    occurred_at=item.occurred_at,
                    is_mock=item.is_mock,
                )
            )
            created["triggers"] += 1

    for topic in intent:
        exists = db.scalar(
            select(IntentSignal.id).where(
                IntentSignal.tenant_id == tenant_id,
                IntentSignal.account_id == account.id,
                IntentSignal.topic == topic.topic,
            )
        )
        if exists is None:
            db.add(
                IntentSignal(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    account_id=account.id,
                    topic=topic.topic,
                    intensity=topic.intensity,
                    source=topic.provider,
                    evidence=topic.evidence,
                    confidence=topic.intensity,
                    impact="high" if topic.intensity >= 60 else "medium",
                    recommended_action="Use the topic in research; do not invent a budget.",
                    occurred_at=datetime.now(UTC),
                    is_mock=topic.is_mock,
                )
            )
            created["intent_signals"] += 1

    for tech in stack:
        exists = db.scalar(
            select(TechnologySignal.id).where(
                TechnologySignal.tenant_id == tenant_id,
                TechnologySignal.account_id == account.id,
                TechnologySignal.technology == tech.technology,
            )
        )
        if exists is None:
            db.add(
                TechnologySignal(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    account_id=account.id,
                    technology=tech.technology,
                    category=tech.category,
                    source=tech.provider,
                    evidence=tech.evidence,
                    confidence=52,
                    impact="medium",
                    recommended_action="Map the stack to AGRAYIAN solutions only if the account confirms it.",
                    occurred_at=datetime.now(UTC),
                    is_mock=tech.is_mock,
                )
            )
            created["technology_signals"] += 1
    return created
