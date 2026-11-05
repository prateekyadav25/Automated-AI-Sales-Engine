"""Install the revenue engine as the product this workspace sells.

Fictional sample data is retired. No outreach is sent.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag import ingest_text
from app.db.session import get_engine, get_session
from app.db.tenant_context import set_tenant_context
from app.models.ai import AIApproval, KnowledgeChunk, KnowledgeSource
from app.models.content import ContentDraft, SellerProfile
from app.models.crm import ICP, Account, Lead, LeadScore
from app.models.identity import Tenant, User
from app.models.integrations import ProviderHealthState
from app.models.lifecycle import Campaign, Product, Sequence, SequenceStep
from app.models.market import AccountSignal, CompetitiveSignal, IntentSignal, Market, MarketSignal
from app.providers.lead_discovery import get_lead_discovery_provider
from app.services.discovery import run_discovery
from app.services.lifecycle import build_forecast
from app.services.orchestrator import process_pending_events
from app.services.sample_data import retire_sample_data

OFFER_NAME = "AGRAYIAN Autonomous Revenue OS"
ICP_NAME = "India B2B revenue teams"
CAMPAIGN_NAME = "India B2B — Revenue OS"
SEQUENCE_NAME = "Revenue OS introduction"
KNOWLEDGE_TITLE = "AGRAYIAN Autonomous Revenue OS — offer"

KNOWLEDGE = """
AGRAYIAN Autonomous Revenue OS is the product. It is one workspace for a company's revenue, from finding the right accounts through renewal and referral.

The lifecycle is Intelligence, Acquire, Sell, Close, Succeed, Retain, Expand, Advocate, and Learn. Intelligence chooses who to sell to. Acquire finds companies and captures inbound interest. Sell prepares conversations and meetings. Close turns a qualified deal into a quote and a contract. Succeed onboards the customer. Retain watches renewal. Expand recommends more only when usage evidence exists. Advocate asks for a referral only after value is confirmed. Learn writes the outcome back into the next cycle.

Autopilot prepares discovery, enrichment, scoring, research, and message drafts. A person approves every send, every ad spend, and every phone dial. Prices, discounts, taxes, scores, and dates are calculated by the system. The model explains them. It does not invent them.

Who it is for: a B2B company in India with about 50 to 1,000 employees and a sales team that already sells to other businesses. The buyer is the founder, chief executive, chief revenue officer, VP of sales, or head of revenue operations. They feel the pain of a CRM that stores names while outreach, content, meetings, quotes, and renewals live somewhere else.

Who it is not for: a company with no sales motion, a consumer brand, or a buyer who wants a chatbot with no record of consent, approval, or audit.

What the buyer gets: the workspace they can sign in to, an ideal customer profile, campaigns and sequences that stay draft until approved, a decision inbox, a pipeline, quotes with list prices, and the post-sale record after a deal is actually won.

Commercial list prices in INR, before tax. One-time setup is 300000 for a company under 200 employees and 400000 for a company of 200 to 1000 employees. The monthly fee starts at 50000 and is raised on the quote as the company gets larger. These are list prices. A quote is created only for a real opportunity.

Nothing on this page is a customer until a real company is discovered, captured with consent, or entered by the team. Example domains and invented bank, hospital, and factory names are not customers.
""".strip()

DRAFTS = (
    (
        "linkedin",
        "One workspace for the whole revenue cycle",
        "Most teams keep names in a CRM and do the real work in five other tools. AGRAYIAN Autonomous Revenue OS runs intelligence, acquire, sell, close, succeed, retain, expand, and advocate in one place. Autopilot prepares the work. A person approves anything that sends, spends, or dials.",
        "See how a revenue team runs on it",
    ),
    (
        "facebook",
        "The draft is ready. The send waits for you.",
        "The revenue engine writes the first version of an email, a post, or a call script from the offer and the ideal customer profile. It does not send that work until someone in the company approves it.",
        "Read the offer",
    ),
    (
        "instagram",
        "Built for B2B teams that already have a sales motion",
        "The buyer is a founder, CRO, or revenue leader at a B2B company in India. The product is the system that finds accounts, prepares conversations, and keeps the customer record after the deal.",
        "Talk to AGRAYIAN",
    ),
)


def _hide(row, now: datetime) -> None:
    if row.deleted_at is None:
        row.deleted_at = now


def _retire_fiction(db: Session, tenant_id, now: datetime) -> int:
    retired = retire_sample_data(db, tenant_id=tenant_id, now=now)
    for model in (MarketSignal, AccountSignal, IntentSignal, CompetitiveSignal):
        for row in db.scalars(select(model).where(model.tenant_id == tenant_id, model.is_mock.is_(True), model.deleted_at.is_(None))):
            _hide(row, now)
    return retired.get(Account.__tablename__, 0)


def _install_icp(db: Session, tenant_id, actor_id) -> ICP:
    icp = db.scalar(select(ICP).where(ICP.tenant_id == tenant_id, ICP.deleted_at.is_(None)).order_by(ICP.is_default.desc()))
    if icp is None:
        icp = ICP(tenant_id=tenant_id, created_by=actor_id, is_default=True)
        db.add(icp)
    icp.name = ICP_NAME
    icp.is_default = True
    icp.industries = "technology,software"
    icp.geographies = "india"
    icp.min_employees = 50
    icp.max_employees = 1000
    icp.personas = "CEO,Founder,CRO,VP Sales,Head of Revenue Operations"
    icp.seniorities = "cxo,vp,director,owner"
    icp.job_functions = "sales"
    icp.keywords = "B2B sales"
    icp.target_companies = ""
    icp.description = (
        "B2B companies in India, about 50 to 1,000 people, that already sell to other businesses. "
        "The buyer is the founder, CEO, CRO, VP of sales, or head of revenue operations. "
        "They have outgrown a CRM that only stores contacts. "
        "They need one system for finding accounts, preparing conversations, quoting, and keeping the customer after the win. "
        "Skip consumer brands and companies with no sales team."
    )
    return icp


def _install_products(db: Session, tenant_id, actor_id) -> None:
    catalog = {
        "CORE": (
            "Revenue OS monthly",
            Decimal("50000"),
            "subscription",
            "Starting monthly price for a company of about 50 to 200 employees. Raise this line on the quote as headcount grows. Do not leave ₹50,000 on a much larger company without editing the quote.",
        ),
        "GOV": (
            "One-time setup, under 200 employees",
            Decimal("300000"),
            "one_time",
            "One-time setup of ₹3,00,000 for a company under 200 employees.",
        ),
        "CS": (
            "One-time setup, 200 to 1,000 employees",
            Decimal("400000"),
            "one_time",
            "One-time setup of ₹4,00,000 for a company of 200 to 1,000 employees.",
        ),
    }
    for sku, (name, price, kind, description) in catalog.items():
        row = db.scalar(select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku, Product.deleted_at.is_(None)))
        if row is None:
            row = Product(tenant_id=tenant_id, created_by=actor_id, sku=sku, currency="INR")
            db.add(row)
        row.name = name
        row.list_price = price
        row.description = description
        row.currency = "INR"
        row.kind = kind


def _install_profile(db: Session, tenant_id, actor_id) -> None:
    profile = db.scalar(select(SellerProfile).where(SellerProfile.tenant_id == tenant_id, SellerProfile.deleted_at.is_(None)))
    if profile is None:
        profile = SellerProfile(tenant_id=tenant_id, created_by=actor_id)
        db.add(profile)
    profile.company_name = "AGRAYIAN AI Labs"
    profile.summary = (
        "AGRAYIAN AI Labs sells the Autonomous Revenue OS. "
        "One workspace runs the revenue cycle. Autopilot prepares the work. A person approves send, spend, and dial."
    )
    profile.audience = "Founders, CEOs, CROs, and revenue leaders at B2B companies in India with a sales team."
    profile.website = "https://agrayianailabs.com"
    profile.proof = "The workspace itself is the product. A company appears as a customer only after a real deal is won."
    profile.capture_url = "https://agrayianailabs.com"


def _install_knowledge(db: Session, tenant_id, actor_id) -> None:
    now = datetime.now(UTC)
    existing = db.scalars(
        select(KnowledgeSource).where(
            KnowledgeSource.tenant_id == tenant_id,
            KnowledgeSource.title == KNOWLEDGE_TITLE,
            KnowledgeSource.deleted_at.is_(None),
        )
    ).all()
    for source in existing:
        source.deleted_at = now
        for chunk in db.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.tenant_id == tenant_id, KnowledgeChunk.source_id == source.id, KnowledgeChunk.deleted_at.is_(None))
        ):
            chunk.deleted_at = now
    ingest_text(db, tenant_id=tenant_id, actor_id=actor_id, title=KNOWLEDGE_TITLE, text=KNOWLEDGE)


def _install_markets(db: Session, tenant_id, actor_id) -> None:
    specs = {
        "India BFSI AI Governance": (
            "India B2B software",
            "technology",
            "india",
            "Software companies in India that sell to other businesses and need one revenue system.",
        ),
        "Gulf Manufacturing Quality": (
            "India B2B services",
            "technology",
            "india",
            "Services firms in India with a named sales team and a CRM that does not run the rest of the cycle.",
        ),
        "APAC Healthcare Systems": (
            "B2B companies ready to replace tool sprawl",
            "software",
            "india",
            "Teams whose outreach, quotes, and renewals sit outside the CRM.",
        ),
    }
    for old_name, (name, industry, geography, description) in specs.items():
        row = db.scalar(select(Market).where(Market.tenant_id == tenant_id, Market.name == old_name, Market.deleted_at.is_(None)))
        if row is None:
            row = db.scalar(select(Market).where(Market.tenant_id == tenant_id, Market.name == name, Market.deleted_at.is_(None)))
        if row is None:
            row = Market(tenant_id=tenant_id, created_by=actor_id)
            db.add(row)
        row.name = name
        row.industry = industry
        row.geography = geography
        row.description = description


def _install_campaign(db: Session, tenant_id, actor_id) -> Campaign:
    row = db.scalar(select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.name == CAMPAIGN_NAME, Campaign.deleted_at.is_(None)))
    if row is None:
        row = Campaign(tenant_id=tenant_id, created_by=actor_id, name=CAMPAIGN_NAME)
        db.add(row)
    row.channel = "outbound"
    row.status = "draft"
    row.objective = "pipeline"
    row.budget = Decimal("0")
    row.notes = (
        "Sell the Autonomous Revenue OS to India B2B revenue leaders. "
        "Budget stays at zero until a person approves spend. No ad is launched from this record."
    )
    return row


STEP_TEMPLATES = {
    1: (
        "We built one workspace for the revenue cycle: find the account, prepare the conversation, "
        "quote the work, and keep the customer after the win. Autopilot drafts. A person approves the send. "
        "Setup is ₹3,00,000 under 200 employees and ₹4,00,000 from 200 employees up. "
        "The monthly fee starts at ₹50,000 and is set from company size before a quote is approved. "
        "If your team still splits that work across a CRM and a pile of tools, I can show you the workspace."
    ),
    2: (
        "Following up on the revenue workspace. Setup is a one-time ₹3,00,000 to ₹4,00,000 depending on company size. "
        "The monthly fee starts at ₹50,000. I will not send a proposal until we know the sales motion and who approves a new system."
    ),
}


def _install_sequence(db: Session, tenant_id, actor_id, icp: ICP, campaign: Campaign) -> None:
    row = db.scalar(select(Sequence).where(Sequence.tenant_id == tenant_id, Sequence.name == SEQUENCE_NAME, Sequence.deleted_at.is_(None)))
    if row is None:
        row = Sequence(tenant_id=tenant_id, created_by=actor_id, name=SEQUENCE_NAME)
        db.add(row)
        db.flush()
        for position, template in STEP_TEMPLATES.items():
            db.add(
                SequenceStep(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    sequence_id=row.id,
                    position=position,
                    delay_days=0 if position == 1 else 4,
                    action_type="email_draft",
                    template=template,
                )
            )
    else:
        for step in db.scalars(select(SequenceStep).where(SequenceStep.sequence_id == row.id, SequenceStep.deleted_at.is_(None))):
            if step.position in STEP_TEMPLATES:
                step.template = STEP_TEMPLATES[step.position]
    row.status = "draft"
    row.channel = "email"
    row.purpose = "sdr"
    row.icp_id = icp.id
    row.campaign_id = campaign.id
    row.offer_key = "revenue-os"


def _install_drafts(db: Session, tenant_id, actor_id) -> None:
    product = db.scalar(select(Product).where(Product.tenant_id == tenant_id, Product.sku == "CORE", Product.deleted_at.is_(None)))
    keep = {item[1] for item in DRAFTS}
    for row in db.scalars(select(ContentDraft).where(ContentDraft.tenant_id == tenant_id, ContentDraft.deleted_at.is_(None))):
        if row.headline not in keep:
            _hide(row, datetime.now(UTC))
    for channel, headline, body, cta in DRAFTS:
        row = db.scalar(
            select(ContentDraft).where(
                ContentDraft.tenant_id == tenant_id,
                ContentDraft.headline == headline,
                ContentDraft.deleted_at.is_(None),
            )
        )
        if row is None:
            row = ContentDraft(tenant_id=tenant_id, created_by=actor_id, channel=channel, kind="post", headline=headline)
            db.add(row)
        row.body = body
        row.cta = cta
        row.status = "draft"
        row.product_id = product.id if product else None
        row.brief = "Sell the Autonomous Revenue OS. Do not publish until a person approves it."
        row.destination_url = "https://agrayianailabs.com"


def _clear_discovery_cooldown(db: Session, tenant_id) -> None:
    row = db.scalar(
        select(ProviderHealthState).where(
            ProviderHealthState.tenant_id == tenant_id,
            ProviderHealthState.provider == "apify",
            ProviderHealthState.deleted_at.is_(None),
        )
    )
    if row is None or row.state != "RATE_LIMITED":
        return
    row.state = "UNKNOWN"
    row.opened_at = None
    row.consecutive_failures = 0
    row.last_error_summary = ""


def _prepare_outreach(db: Session, tenant_id, actor_id) -> str:
    leads = list(
        db.scalars(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.deleted_at.is_(None),
                Lead.source == "ai_discovery",
                Lead.email != "",
            )
        ).all()
    )
    if not leads:
        return "Discovery stored no lead with an email address, so no introduction was queued."
    best = leads[0]
    best_total = -1
    for lead in leads:
        score = db.scalar(
            select(LeadScore).where(LeadScore.tenant_id == tenant_id, LeadScore.lead_id == lead.id, LeadScore.deleted_at.is_(None)).order_by(LeadScore.created_at.desc())
        )
        total = score.total if score is not None else 0
        if total >= best_total:
            best = lead
            best_total = total
    company = best.company_name or "your team"
    body = (
        f"Hello {best.first_name},\n\n"
        "AGRAYIAN AI Labs runs the whole revenue cycle in one workspace: find the account, prepare the conversation, "
        "quote the work, and keep the customer after the win. Autopilot prepares the draft. A person approves the send.\n\n"
        "Setup is ₹3,00,000 for a company under 200 people and ₹4,00,000 from 200 people up. "
        "The monthly fee starts at ₹50,000 and is set from company size before a quote is approved.\n\n"
        f"If {company} is still splitting that work across a CRM and other tools, I can show you the workspace."
    )
    key = f"offer-intro:{best.id}"
    existing = db.scalar(
        select(AIApproval).where(AIApproval.tenant_id == tenant_id, AIApproval.idempotency_key == key, AIApproval.deleted_at.is_(None))
    )
    if existing is None:
        db.add(
            AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="email.send",
                title=f"Introduction for {best.first_name} {best.last_name} at {company}",
                payload_json=json.dumps(
                    {
                        "lead_id": str(best.id),
                        "subject": "One workspace for your revenue cycle",
                        "body": body,
                        "why": "Highest-scored discovered lead with an email address.",
                        "evidence": "LinkedIn discovery. Email consent is not on file.",
                        "risk": "Approve does not send until email consent is recorded and Gmail is connected.",
                        "expected_outcome": "First-touch email after consent and approval.",
                    }
                ),
                status="pending",
                entity_type="lead",
                entity_id=str(best.id),
                idempotency_key=key,
            )
        )
    return (
        f"Prepared an introduction for {best.first_name} {best.last_name} at {company}. "
        "It is waiting in Decision inbox. The send stays blocked until email consent is recorded."
    )


def install_offer(db: Session, *, discover: bool = True) -> dict[str, str | int]:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == "agrayian"))
    if tenant is None:
        raise RuntimeError("AGRAYIAN tenant is not seeded")
    set_tenant_context(db, tenant.id)
    actor = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == "admin@agrayian.demo"))
    if actor is None:
        raise RuntimeError("AGRAYIAN admin user is missing")
    now = datetime.now(UTC)
    retired = _retire_fiction(db, tenant.id, now)
    icp = _install_icp(db, tenant.id, actor.id)
    db.flush()
    _install_products(db, tenant.id, actor.id)
    _install_profile(db, tenant.id, actor.id)
    _install_knowledge(db, tenant.id, actor.id)
    _install_markets(db, tenant.id, actor.id)
    campaign = _install_campaign(db, tenant.id, actor.id)
    db.flush()
    _install_sequence(db, tenant.id, actor.id, icp, campaign)
    _install_drafts(db, tenant.id, actor.id)
    build_forecast(db, tenant.id, actor.id)
    health = get_lead_discovery_provider(db, tenant.id).health()
    discovered = 0
    outreach = "Discovery did not run."
    reason = str(health.get("reason") or "") if discover else "Discovery was skipped."
    if discover and health.get("connected") and not health.get("is_mock"):
        _clear_discovery_cooldown(db, tenant.id)
        result = run_discovery(db, tenant_id=tenant.id, actor_id=actor.id, correlation_id="offer-install-30")
        process_pending_events(db, tenant_id=tenant.id, actor_id=actor.id)
        discovered = int(result.get("created", 0))
        reason = str(result.get("reason") or reason)
        outreach = _prepare_outreach(db, tenant.id, actor.id) if discovered else "No new lead was stored."
    return {"retired_accounts": retired, "icp": icp.name, "discovered": discovered, "discovery": reason, "outreach": outreach}


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.offer_install", description=__doc__)
    parser.add_argument("--skip-discovery", action="store_true", help="Do not start a lead discovery run.")
    args = parser.parse_args()
    get_engine()
    db = get_session()
    try:
        summary = install_offer(db, discover=not args.skip_discovery)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(
        f"Installed {OFFER_NAME}. ICP={summary['icp']}. "
        f"Retired fictional accounts={summary['retired_accounts']}. "
        f"Discovered leads={summary['discovered']}. {summary['discovery']} {summary['outreach']}"
    )


if __name__ == "__main__":
    main()
