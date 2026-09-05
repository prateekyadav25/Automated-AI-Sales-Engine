"""Idempotent demo seed. Fictional companies and people only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.ai.rag import ingest_text
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_engine, get_session
from app.models import *  # noqa: F403
from app.models.acquisition import InboundCapture
from app.models.ai import Prompt
from app.models.autonomy import AutopilotSettings
from app.models.crm import ICP, Account, Contact, Customer, Lead, Opportunity, Task
from app.models.identity import (
    FeatureFlag,
    Permission,
    Role,
    RolePermission,
    Team,
    Tenant,
    Territory,
    User,
    UserRole,
)
from app.models.lifecycle import (
    AbmPlay,
    AdvocacyAsset,
    Campaign,
    CampaignMember,
    Conversation,
    ForecastSnapshot,
    MeetingRecord,
    ModelCard,
    Playbook,
    Product,
    Quote,
    Referral,
    Sequence,
    SequenceStep,
)
from app.models.market import AccountSignal, CompetitiveSignal, IntentSignal, Market, MarketSignal, TriggerEvent
from app.services.crm import close_won
from app.services.lifecycle import (
    build_forecast,
    create_quote,
    enroll_sequence,
    fill_whitespace,
    run_playbook,
    score_deal,
)
from app.services.market import score_market
from app.services.rbac import PERMISSIONS, ROLE_PERMISSIONS
from app.services.scoring import score_lead

DEMO_PASSWORD = "Agrarian!Demo1"

FLAGS = [
    ("ENABLE_AI_COPILOT", True, "Global copilot"),
    ("ENABLE_KNOWLEDGE_RAG", True, "Knowledge retrieval"),
    ("ENABLE_AUTO_EMAIL", False, "Auto send email"),
    ("ENABLE_AI_SDR", False, "AI SDR sequences"),
    ("ENABLE_VOICE_AGENT", False, "Voice agent"),
    ("ENABLE_MARKET_INTELLIGENCE", True, "Market engine"),
    ("ENABLE_ACQUISITION", True, "Inbound capture and dedupe"),
    ("ENABLE_DEAL_COACH", True, "Deal coach rules"),
    ("ENABLE_CUSTOMER_HEALTH", True, "CS health rules"),
    ("ENABLE_CHURN_PREDICTION", False, "Churn ML"),
    ("ENABLE_FORECAST_ML", False, "Forecast ML"),
    ("ENABLE_LEAD_DISCOVERY", True, "Apify or labeled mock discovery"),
    ("ENABLE_AUTOPILOT", True, "Persisted autonomous cycle"),
]


def _ensure_permissions(db) -> dict[str, Permission]:
    existing = {row.key: row for row in db.scalars(select(Permission)).all()}
    for key, description in PERMISSIONS:
        if key not in existing:
            row = Permission(key=key, description=description)
            db.add(row)
            existing[key] = row
    db.flush()
    return existing


def _ensure_roles(db, tenant_id, permissions: dict[str, Permission]) -> dict[str, Role]:
    roles = {
        row.name: row
        for row in db.scalars(select(Role).where(Role.tenant_id == tenant_id)).all()
    }
    for name, keys in ROLE_PERMISSIONS.items():
        role = roles.get(name)
        if role is None:
            role = Role(tenant_id=tenant_id, name=name, description=name)
            db.add(role)
            db.flush()
            roles[name] = role
        for key in keys:
            perm = permissions.get(key)
            if perm is None:
                continue
            exists = db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id, RolePermission.permission_id == perm.id
                )
            )
            if exists is None:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    return roles


def _user(db, tenant_id, email, name, role: Role, super_admin: bool = False) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            tenant_id=tenant_id,
            email=email,
            name=name,
            password_hash=hash_password(DEMO_PASSWORD),
            is_super_admin=super_admin,
        )
        db.add(user)
        db.flush()
    assigned = db.scalar(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
    )
    if assigned is None:
        db.add(UserRole(user_id=user.id, role_id=role.id))
    return user


def _flags(db, tenant_id) -> None:
    for key, enabled, description in FLAGS:
        row = db.scalar(select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id, FeatureFlag.key == key))
        if row is None:
            db.add(FeatureFlag(tenant_id=tenant_id, key=key, enabled=enabled, description=description))
        elif key in {
            "ENABLE_MARKET_INTELLIGENCE",
            "ENABLE_ACQUISITION",
            "ENABLE_DEAL_COACH",
            "ENABLE_CUSTOMER_HEALTH",
            "ENABLE_LEAD_DISCOVERY",
            "ENABLE_AUTOPILOT",
        }:
            row.enabled = True


def _autopilot_settings(db, tenant_id, actor_id) -> None:
    row = db.scalar(select(AutopilotSettings).where(AutopilotSettings.tenant_id == tenant_id, AutopilotSettings.deleted_at.is_(None)))
    if row is None:
        db.add(AutopilotSettings(tenant_id=tenant_id, created_by=actor_id, enabled=True, discovery_enabled=True))


def _prompts(db, tenant_id, actor_id) -> None:
    templates = {
        "copilot": "You are the AGRAYIAN copilot. Use only tool observations. Cite knowledge. Do not invent KPIs.",
        "account_research": "You are AccountResearchAgent. Use tools only. No invented financials or news.",
        "lead_summary": "Summarize the lead from tools. Explain scores. Do not fabricate numbers.",
        "opportunity_summary": "Summarize the opportunity. Do not change commercial terms.",
        "email_draft": "Draft email only. Never claim it was sent. Honor opt-out.",
        "knowledge": "Answer from retrieved chunks. If empty, abstain.",
    }
    for key, template in templates.items():
        exists = db.scalar(
            select(Prompt).where(Prompt.tenant_id == tenant_id, Prompt.prompt_key == key)
        )
        if exists is None:
            db.add(
                Prompt(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    prompt_key=key,
                    name=key,
                    version="1",
                    agent=key,
                    template=template,
                    status="approved",
                )
            )


def seed() -> None:
    get_engine()
    Base.metadata.create_all(bind=get_engine())
    db = get_session()
    try:
        permissions = _ensure_permissions(db)
        agrayian = db.scalar(select(Tenant).where(Tenant.slug == "agrayian"))
        if agrayian is None:
            agrayian = Tenant(name="AGRAYIAN AI Labs", slug="agrayian")
            db.add(agrayian)
            db.flush()
        northline = db.scalar(select(Tenant).where(Tenant.slug == "northline"))
        if northline is None:
            northline = Tenant(name="Northline Demo", slug="northline")
            db.add(northline)
            db.flush()

        roles_a = _ensure_roles(db, agrayian.id, permissions)
        roles_b = _ensure_roles(db, northline.id, permissions)
        admin = _user(db, agrayian.id, "admin@agrayian.demo", "Asha Menon", roles_a["Tenant Admin"], True)
        seller = _user(db, agrayian.id, "seller@agrayian.demo", "Rohan Iyer", roles_a["Sales Rep"])
        _user(db, agrayian.id, "readonly@agrayian.demo", "Priya Nair", roles_a["Read Only"])
        _user(db, northline.id, "admin@northline.demo", "James Cole", roles_b["Tenant Admin"])
        _flags(db, agrayian.id)
        _flags(db, northline.id)
        _autopilot_settings(db, agrayian.id, admin.id)
        _autopilot_settings(db, northline.id, admin.id)
        _prompts(db, agrayian.id, admin.id)
        _prompts(db, northline.id, admin.id)

        if db.scalar(select(Team).where(Team.tenant_id == agrayian.id)) is None:
            db.add(Team(tenant_id=agrayian.id, name="Enterprise Sales", team_type="sales"))
        if db.scalar(select(Territory).where(Territory.tenant_id == agrayian.id)) is None:
            db.add(Territory(tenant_id=agrayian.id, name="India Enterprise", region="APAC"))

        icp = db.scalar(select(ICP).where(ICP.tenant_id == agrayian.id))
        if icp is None:
            icp = ICP(
                tenant_id=agrayian.id,
                created_by=admin.id,
                name="Enterprise AI Transformation",
                industries="bfsi,government,manufacturing,healthcare,retail,technology,enterprise",
                geographies="india,uae,southeast asia",
                min_employees=200,
                description="Large organizations adopting AI with executive sponsors.",
                is_default=True,
            )
            db.add(icp)
            db.flush()

        accounts_spec = [
            ("Meridian Bank", "bfsi", "meridianbank.example", "India", 12000, Decimal("2400000000")),
            ("Helios Public Works", "government", "heliosgov.example", "India", 4800, None),
            ("ForgeLine Manufacturing", "manufacturing", "forgelin.example", "UAE", 3200, Decimal("410000000")),
            ("Nimbus Health Systems", "healthcare", "nimbushealth.example", "India", 2100, Decimal("180000000")),
            ("Harbor Retail Group", "retail", "harborretail.example", "Singapore", 9000, Decimal("900000000")),
            ("Vertex Cloud Technologies", "technology", "vertexcloud.example", "India", 850, Decimal("62000000")),
            ("Northwind Enterprise Holdings", "enterprise", "northwindent.example", "UK", 15000, Decimal("3100000000")),
        ]
        accounts: list[Account] = []
        for name, industry, domain, country, employees, revenue in accounts_spec:
            account = db.scalar(
                select(Account).where(Account.tenant_id == agrayian.id, Account.name == name)
            )
            if account is None:
                account = Account(
                    tenant_id=agrayian.id,
                    created_by=admin.id,
                    name=name,
                    industry=industry,
                    website=f"https://{domain}",
                    domain=domain,
                    hq_country=country,
                    employee_count=employees,
                    annual_revenue=revenue,
                    ownership="prospect",
                    target_tier="tier_1" if employees > 5000 else "tier_2",
                    notes="Fictional demo account for AGRAYIAN Revenue OS.",
                )
                db.add(account)
                db.flush()
            accounts.append(account)

        if db.scalar(select(Account).where(Account.tenant_id == northline.id)) is None:
            db.add(
                Account(
                    tenant_id=northline.id,
                    name="Northline Isolated Account",
                    industry="technology",
                    domain="northline.example",
                    hq_country="US",
                )
            )

        contacts_spec = [
            (0, "Lina", "Kapoor", "CIO", "economic_buyer"),
            (0, "Vikram", "Shah", "Head of Data", "champion"),
            (1, "Anita", "Rao", "Director of Digital", "decision_maker"),
            (2, "Omar", "Haddad", "CTO", "technical_buyer"),
            (3, "Meera", "Das", "CISO", "blocker"),
            (4, "Wei", "Tan", "COO", "influencer"),
            (5, "Arjun", "Patel", "Head of AI", "champion"),
        ]
        if db.scalar(select(Contact).where(Contact.tenant_id == agrayian.id)) is None:
            for idx, first, last, title, role in contacts_spec:
                db.add(
                    Contact(
                        tenant_id=agrayian.id,
                        created_by=seller.id,
                        account_id=accounts[idx].id,
                        first_name=first,
                        last_name=last,
                        email=f"{first.lower()}.{last.lower()}@{accounts[idx].domain}",
                        title=title,
                        seniority="executive",
                        buying_role=role,
                        consent_email=True,
                    )
                )

        if db.scalar(select(Lead).where(Lead.tenant_id == agrayian.id)) is None:
            leads = [
                ("Jane", "D'Souza", "CIO", accounts[0], 80, 70, True),
                ("Farid", "Khan", "IT Director", accounts[1], 55, 40, True),
                ("Sofia", "Almeida", "Head of Analytics", accounts[3], 40, 30, False),
                ("Kenji", "Mori", "Procurement Lead", accounts[6], 20, 10, False),
            ]
            for first, last, title, account, intent, engagement, trigger in leads:
                lead = Lead(
                    tenant_id=agrayian.id,
                    created_by=seller.id,
                    account_id=account.id,
                    first_name=first,
                    last_name=last,
                    email=f"{first.lower()}.{last.lower()}@{account.domain}",
                    company_name=account.name,
                    title=title,
                    source="inbound",
                    channel="website",
                    status="new",
                    consent_email=True,
                    intent_score=intent,
                    engagement_score=engagement,
                    has_buying_trigger=trigger,
                )
                db.add(lead)
                db.flush()
                score_lead(db, lead, emit=False)

        if db.scalar(select(Opportunity).where(Opportunity.tenant_id == agrayian.id)) is None:
            opps = [
                (accounts[0], "Meridian AI Governance Program", "proposal", Decimal("420000"), 60),
                (accounts[2], "ForgeLine Predictive Quality", "discovery", Decimal("180000"), 20),
                (accounts[5], "Vertex Copilot Pilot", "demo", Decimal("95000"), 40),
                (accounts[4], "Harbor Personalization Suite", "qualification", Decimal("260000"), 10),
            ]
            for account, name, stage, amount, prob in opps:
                db.add(
                    Opportunity(
                        tenant_id=agrayian.id,
                        created_by=seller.id,
                        owner_id=seller.id,
                        account_id=account.id,
                        name=name,
                        stage=stage,
                        amount=amount,
                        probability=prob,
                        expected_close=(datetime.now(UTC) + timedelta(days=45)).date(),
                        next_step="Schedule economic-buyer review",
                    )
                )
            db.add(
                Task(
                    tenant_id=agrayian.id,
                    created_by=seller.id,
                    owner_id=seller.id,
                    title="Prepare Meridian proposal walkthrough",
                    description="Use account research brief before the meeting.",
                    status="open",
                    priority="high",
                    due_at=datetime.now(UTC) + timedelta(days=2),
                    entity_type="account",
                    entity_id=str(accounts[0].id),
                    source="human",
                )
            )

        if db.scalar(select(Market).where(Market.tenant_id == agrayian.id)) is None:
            markets = [
                ("India BFSI AI Governance", "bfsi", "india", "Banks and insurers adopting governed AI."),
                ("Gulf Manufacturing Quality", "manufacturing", "uae", "Discrete manufacturers seeking predictive quality."),
                ("APAC Healthcare Systems", "healthcare", "india", "Hospital groups modernizing clinical operations."),
            ]
            market_rows = []
            for name, industry, geography, description in markets:
                market = Market(
                    tenant_id=agrayian.id,
                    created_by=admin.id,
                    name=name,
                    industry=industry,
                    geography=geography,
                    description=description,
                )
                db.add(market)
                db.flush()
                market_rows.append(market)
            db.add(
                MarketSignal(
                    tenant_id=agrayian.id,
                    created_by=admin.id,
                    market_id=market_rows[0].id,
                    signal_type="regulation",
                    title="RBI-style model-risk guidance in buyer conversations",
                    source="seed",
                    evidence="Fictional seed signal for the India BFSI market. Not a live regulatory feed.",
                    confidence=70,
                    impact="high",
                    recommended_action="Prioritize Meridian Bank research with governance language.",
                    occurred_at=datetime.now(UTC),
                    is_mock=True,
                )
            )
            db.add(
                AccountSignal(
                    tenant_id=agrayian.id,
                    created_by=admin.id,
                    account_id=accounts[0].id,
                    signal_type="hiring",
                    title="Meridian posted a Head of Model Risk role",
                    source="seed",
                    evidence="Fictional hiring trigger seeded for demo. Confirm before outreach.",
                    confidence=68,
                    impact="high",
                    recommended_action="Ask the CIO about model-risk staffing, do not invent a budget.",
                    occurred_at=datetime.now(UTC) - timedelta(days=12),
                    is_mock=True,
                )
            )
            db.add(
                IntentSignal(
                    tenant_id=agrayian.id,
                    created_by=admin.id,
                    account_id=accounts[0].id,
                    topic="AI governance",
                    intensity=74,
                    source="seed",
                    evidence="Seeded intent topic. Mock provider intensity, not a paid intent vendor.",
                    confidence=74,
                    impact="high",
                    recommended_action="Use in meeting prep only as a hypothesis.",
                    occurred_at=datetime.now(UTC) - timedelta(days=5),
                    is_mock=True,
                )
            )
            db.add(
                CompetitiveSignal(
                    tenant_id=agrayian.id,
                    created_by=admin.id,
                    account_id=accounts[5].id,
                    competitor="Generic Copilot Inc",
                    movement="evaluation",
                    source="seed",
                    evidence="Fictional competitor mention on Vertex Cloud.",
                    confidence=48,
                    impact="medium",
                    recommended_action="Differentiate on governance, not price invention.",
                    occurred_at=datetime.now(UTC) - timedelta(days=20),
                    is_mock=True,
                )
            )
            db.add(
                TriggerEvent(
                    tenant_id=agrayian.id,
                    created_by=admin.id,
                    account_id=accounts[2].id,
                    trigger_type="rfp",
                    title="ForgeLine opened a predictive-quality RFP window",
                    body="Fictional procurement trigger. Empty until a live news provider is configured.",
                    source="seed",
                    evidence="Seeded RFP trigger for manufacturing.",
                    confidence=60,
                    impact="high",
                    recommended_action="Confirm dates with Omar Haddad before committing a proposal date.",
                    occurred_at=datetime.now(UTC) - timedelta(days=8),
                    is_mock=True,
                )
            )
            for market in market_rows:
                score_market(db, market)
            if db.scalar(select(InboundCapture).where(InboundCapture.tenant_id == agrayian.id)) is None:
                first_lead = db.scalar(select(Lead).where(Lead.tenant_id == agrayian.id))
                if first_lead is not None:
                    db.add(
                        InboundCapture(
                            tenant_id=agrayian.id,
                            created_by=admin.id,
                            lead_id=first_lead.id,
                            first_name=first_lead.first_name,
                            last_name=first_lead.last_name,
                            email=first_lead.email,
                            company_name=first_lead.company_name,
                            title=first_lead.title,
                            source="inbound",
                            channel="website",
                            campaign="governed-ai",
                            utm_source="organic",
                            utm_medium="web",
                            consent_email=True,
                            status="accepted",
                            captured_at=datetime.now(UTC) - timedelta(days=3),
                        )
                    )

        _seed_lifecycle(db, agrayian.id, admin.id, seller.id, accounts)

        existing_knowledge = db.scalar(
            select(Prompt).where(Prompt.tenant_id == agrayian.id, Prompt.prompt_key == "copilot")
        )
        from app.models.ai import KnowledgeSource

        if db.scalar(select(KnowledgeSource).where(KnowledgeSource.tenant_id == agrayian.id)) is None:
            ingest_text(
                db,
                tenant_id=agrayian.id,
                actor_id=admin.id,
                title="AGRAYIAN AI Labs offering overview",
                text=(
                    "AGRAYIAN AI Labs helps enterprises adopt AI with governance, custom AI systems, "
                    "data modernization, AI CoE design, and industry solutions for BFSI, government, "
                    "manufacturing, healthcare and retail. Approved claim: we reduce time-to-value for "
                    "AI programs through governed delivery. Prohibited claim: guaranteed regulatory approval."
                ),
            )
        _ = existing_knowledge
        db.commit()
        print("Seed complete")
    finally:
        db.close()


def _seed_lifecycle(db, tenant_id, admin_id, seller_id, accounts: list[Account]) -> None:
    if db.scalar(select(Campaign).where(Campaign.tenant_id == tenant_id)) is None:
        inbound = Campaign(
            tenant_id=tenant_id,
            created_by=admin_id,
            name="Governed AI inbound",
            channel="inbound",
            status="live",
            objective="pipeline",
            budget=Decimal("25000"),
            spent=Decimal("4100"),
            notes="Fictional campaign. Spend is seeded, not a live ads ledger.",
        )
        abm = Campaign(
            tenant_id=tenant_id,
            created_by=admin_id,
            name="Manufacturing ABM",
            channel="abm",
            status="live",
            objective="meetings",
            budget=Decimal("18000"),
            spent=Decimal("2200"),
        )
        linkedin = Campaign(
            tenant_id=tenant_id,
            created_by=admin_id,
            name="LinkedIn discovery (draft)",
            channel="linkedin",
            status="draft",
            objective="pipeline",
            budget=Decimal("5000"),
            spent=Decimal("0"),
            notes="Draft paid motion. Launch queues Approvals. Spend stays 0 until a live provider returns a figure.",
        )
        db.add_all([inbound, abm, linkedin])
        db.flush()
        db.add(CampaignMember(tenant_id=tenant_id, created_by=admin_id, campaign_id=inbound.id, account_id=accounts[0].id))
        db.add(CampaignMember(tenant_id=tenant_id, created_by=admin_id, campaign_id=abm.id, account_id=accounts[2].id))
        db.add(
            AbmPlay(
                tenant_id=tenant_id,
                created_by=admin_id,
                account_id=accounts[0].id,
                name="Meridian governance land",
                thesis="CIO and Head of Data are staffed. Do not invent a budget.",
                status="active",
            )
        )
    if db.scalar(select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.channel == "linkedin")) is None:
        db.add(
            Campaign(
                tenant_id=tenant_id,
                created_by=admin_id,
                name="LinkedIn discovery (draft)",
                channel="linkedin",
                status="draft",
                objective="pipeline",
                budget=Decimal("5000"),
                spent=Decimal("0"),
                notes="Draft paid motion. Launch queues Approvals. Spend stays 0 until a live provider returns a figure.",
            )
        )

    if db.scalar(select(Sequence).where(Sequence.tenant_id == tenant_id)) is None:
        sequence = Sequence(
            tenant_id=tenant_id,
            created_by=admin_id,
            name="Enterprise CIO cadence",
            channel="email",
            status="live",
            purpose="sdr",
        )
        db.add(sequence)
        db.flush()
        db.add_all(
            [
                SequenceStep(
                    tenant_id=tenant_id,
                    created_by=admin_id,
                    sequence_id=sequence.id,
                    position=1,
                    delay_days=0,
                    action_type="email_draft",
                    template="Draft a governance-first intro. Do not claim it was sent.",
                ),
                SequenceStep(
                    tenant_id=tenant_id,
                    created_by=admin_id,
                    sequence_id=sequence.id,
                    position=2,
                    delay_days=3,
                    action_type="task",
                    template="Call the champion. Confirm buying trigger before the next draft.",
                ),
                SequenceStep(
                    tenant_id=tenant_id,
                    created_by=admin_id,
                    sequence_id=sequence.id,
                    position=3,
                    delay_days=7,
                    action_type="email_draft",
                    template="Share a meeting-prep outline. No invented case study metrics.",
                ),
            ]
        )
        lead = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.email.ilike("%jane%")))
        if lead is not None:
            enroll_sequence(db, tenant_id=tenant_id, actor_id=seller_id, sequence=sequence, lead=lead)

    if db.scalar(select(Conversation).where(Conversation.tenant_id == tenant_id)) is None:
        db.add(
            Conversation(
                tenant_id=tenant_id,
                created_by=seller_id,
                channel="chat",
                account_id=accounts[0].id,
                subject="Meridian website chat",
                status="closed",
                outcome="meeting_requested",
                sentiment="positive",
                consent=True,
                provider="human",
                is_mock=False,
                transcript="Visitor asked about model-risk documentation. No live telephony.",
                summary="Consented chat. Route to meeting prep, not a fabricated budget.",
            )
        )
        meridian_opp = db.scalar(
            select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.name.ilike("%Meridian%"))
        )
        db.add(
            MeetingRecord(
                tenant_id=tenant_id,
                created_by=seller_id,
                account_id=accounts[0].id,
                opportunity_id=meridian_opp.id if meridian_opp else None,
                title="Meridian discovery with CIO",
                occurred_at=datetime.now(UTC) - timedelta(days=4),
                summary="Discussed governance staffing. Amount stayed on the opportunity record.",
                next_steps="Confirm economic-buyer review date.",
                provider="human",
            )
        )

    products = db.scalars(select(Product).where(Product.tenant_id == tenant_id)).all()
    if not products:
        catalog = [
            ("CORE", "AGRAYIAN Core Platform", "subscription", Decimal("120000")),
            ("GOV", "Governance Pack", "subscription", Decimal("48000")),
            ("CS", "Success Desk", "subscription", Decimal("36000")),
        ]
        products = []
        for sku, name, kind, price in catalog:
            row = Product(tenant_id=tenant_id, created_by=admin_id, sku=sku, name=name, kind=kind, list_price=price)
            db.add(row)
            db.flush()
            products.append(row)

    if db.scalar(select(Quote).where(Quote.tenant_id == tenant_id)) is None:
        meridian_opp = db.scalar(
            select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.name.ilike("%Meridian%"))
        )
        if meridian_opp is not None:
            create_quote(
                db,
                tenant_id=tenant_id,
                actor_id=seller_id,
                opportunity=meridian_opp,
                discount_pct=8,
                tax_pct=0,
                lines=[
                    {"product_id": products[0].id, "quantity": 1, "unit_price": products[0].list_price},
                    {"product_id": products[1].id, "quantity": 1, "unit_price": products[1].list_price},
                ],
            )

    if db.scalar(select(Customer).where(Customer.tenant_id == tenant_id)) is None:
        helios = db.scalar(
            select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.name == "Helios Digital Core")
        )
        if helios is None:
            helios = Opportunity(
                tenant_id=tenant_id,
                created_by=seller_id,
                owner_id=seller_id,
                account_id=accounts[1].id,
                name="Helios Digital Core",
                stage="commit",
                amount=Decimal("150000"),
                probability=90,
                expected_close=datetime.now(UTC).date(),
                next_step="Legal paper complete",
            )
            db.add(helios)
            db.flush()
        close_won(db, tenant_id=tenant_id, actor_id=admin_id, opportunity_id=helios.id)

    harbor = db.scalar(
        select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.name.ilike("%Harbor%"))
    )
    if harbor is not None:
        harbor.next_step = ""
        harbor.expected_close = (datetime.now(UTC) - timedelta(days=5)).date()

    for opp in db.scalars(
        select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.deleted_at.is_(None), Opportunity.stage.notin_(["closed_won", "closed_lost"]))
    ):
        score_deal(db, tenant_id, opp)

    if db.scalar(select(ForecastSnapshot).where(ForecastSnapshot.tenant_id == tenant_id)) is None:
        build_forecast(db, tenant_id, admin_id)

    fill_whitespace(db, tenant_id=tenant_id, actor_id=admin_id, account=accounts[0], products=products)
    fill_whitespace(db, tenant_id=tenant_id, actor_id=admin_id, account=accounts[4], products=products)

    if db.scalar(select(AdvocacyAsset).where(AdvocacyAsset.tenant_id == tenant_id)) is None:
        db.add(
            AdvocacyAsset(
                tenant_id=tenant_id,
                created_by=admin_id,
                account_id=accounts[1].id,
                kind="reference",
                readiness=62,
                status="warming",
                notes="Helios can speak to public-sector delivery after onboarding. Not a published case study.",
            )
        )
        db.add(
            Referral(
                tenant_id=tenant_id,
                created_by=admin_id,
                referrer_account_id=accounts[1].id,
                referred_name="Coastal Ports Authority",
                email="cio@coastalports.example",
                status="new",
            )
        )

    if db.scalar(select(ModelCard).where(ModelCard.tenant_id == tenant_id)) is None:
        cards = [
            ("Lead score", "qualification", "100-pt deterministic score. last_trained is null."),
            ("Market attractiveness", "intelligence", "Rules over industry, geography, and seeded signals."),
            ("Deal risk", "pipeline", "Flags missing buyer, stall, slip, competitor, empty next step."),
            ("Health score", "success", "Onboarding + tasks + ARR + labeled mock usage."),
            ("Forecast snapshot", "forecast", "Committed/weighted from open pipeline SQL. Not ML."),
        ]
        for name, purpose, notes in cards:
            db.add(
                ModelCard(
                    tenant_id=tenant_id,
                    created_by=admin_id,
                    name=name,
                    purpose=purpose,
                    version="rules-v1",
                    status="production_rules",
                    notes=notes,
                )
            )

    if db.scalar(select(Playbook).where(Playbook.tenant_id == tenant_id)) is None:
        stall = Playbook(
            tenant_id=tenant_id,
            created_by=admin_id,
            name="Stall rescue",
            trigger_event="deal.stall",
            autonomy_level=1,
            actions_json='[{"type":"create_task","title":"Break the stall","body":"Confirm next step with the champion.","priority":"high"}]',
        )
        handoff = Playbook(
            tenant_id=tenant_id,
            created_by=admin_id,
            name="Closed-won handoff",
            trigger_event="deal.won",
            autonomy_level=1,
            actions_json='[{"type":"write_activity","title":"Handoff noted","body":"Success plan minted by close-won."},{"type":"create_task","title":"Book kickoff"}]',
        )
        db.add_all([stall, handoff])
        db.flush()
        if harbor is not None:
            run_playbook(
                db,
                tenant_id=tenant_id,
                actor_id=admin_id,
                playbook=stall,
                entity_type="opportunity",
                entity_id=str(harbor.id),
            )


if __name__ == "__main__":
    seed()
