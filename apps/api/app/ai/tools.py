import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag import retrieve
from app.models.autonomy import AutonomousRun, AutonomousRunStep
from app.models.crm import Account, Contact, Customer, Lead, Opportunity
from app.services.crm import add_activity
from app.services.query import get_owned
from app.services.voice import extract_meeting_notes


@dataclass
class ToolContext:
    db: Session
    tenant_id: UUID
    actor_id: UUID
    permissions: set[str]


@dataclass
class ToolSpec:
    name: str
    description: str
    required_permission: str
    action_level: int
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


def _account_payload(account: Account) -> dict[str, Any]:
    return {
        "id": str(account.id),
        "name": account.name,
        "industry": account.industry,
        "domain": account.domain,
        "hq_country": account.hq_country,
        "employee_count": account.employee_count,
        "annual_revenue": str(account.annual_revenue) if account.annual_revenue is not None else None,
        "ownership": account.ownership,
        "notes": account.notes,
    }


def tool_get_account(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    account = get_owned(ctx.db, Account, ctx.tenant_id, UUID(args["account_id"]))
    return _account_payload(account)


def tool_search_accounts(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    q = (args.get("q") or "").lower()
    rows = ctx.db.scalars(
        select(Account).where(Account.tenant_id == ctx.tenant_id, Account.deleted_at.is_(None))
    ).all()
    matched = [row for row in rows if q in row.name.lower() or q in row.industry.lower()]
    return {"accounts": [_account_payload(row) for row in matched[:10]]}


def tool_get_lead(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    lead = get_owned(ctx.db, Lead, ctx.tenant_id, UUID(args["lead_id"]))
    return {
        "id": str(lead.id),
        "name": f"{lead.first_name} {lead.last_name}",
        "email": lead.email,
        "title": lead.title,
        "company_name": lead.company_name,
        "status": lead.status,
        "source": lead.source,
        "consent_email": lead.consent_email,
        "opt_out": lead.opt_out,
        "notes": lead.notes,
    }


def tool_get_opportunity(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    opp = get_owned(ctx.db, Opportunity, ctx.tenant_id, UUID(args["opportunity_id"]))
    return {
        "id": str(opp.id),
        "name": opp.name,
        "stage": opp.stage,
        "amount": str(opp.amount),
        "probability": opp.probability,
        "next_step": opp.next_step,
        "account_id": str(opp.account_id),
    }


def tool_get_customer(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    customer = get_owned(ctx.db, Customer, ctx.tenant_id, UUID(args["customer_id"]))
    return {
        "id": str(customer.id),
        "account_id": str(customer.account_id),
        "status": customer.status,
        "arr": str(customer.arr),
    }


def tool_retrieve_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    hits = retrieve(ctx.db, tenant_id=ctx.tenant_id, query=args.get("query", ""), limit=5)
    return {"hits": hits}


def tool_create_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    activity = add_activity(
        ctx.db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.actor_id,
        entity_type=args["entity_type"],
        entity_id=str(args["entity_id"]),
        activity_type="note",
        title=args.get("title", "AI note"),
        body=args.get("body", ""),
        actor_type="ai",
    )
    ctx.db.flush()
    return {"activity_id": str(activity.id)}


def tool_list_signals(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.market import AccountSignal, IntentSignal, TriggerEvent

    account_id = args.get("account_id")
    signals = []
    stmt = select(AccountSignal).where(AccountSignal.tenant_id == ctx.tenant_id, AccountSignal.deleted_at.is_(None))
    if account_id:
        stmt = stmt.where(AccountSignal.account_id == UUID(account_id))
    for row in ctx.db.scalars(stmt.limit(8)):
        signals.append({"kind": "account", "title": row.title, "confidence": row.confidence, "source": row.source, "is_mock": row.is_mock})
    intent_stmt = select(IntentSignal).where(IntentSignal.tenant_id == ctx.tenant_id, IntentSignal.deleted_at.is_(None))
    if account_id:
        intent_stmt = intent_stmt.where(IntentSignal.account_id == UUID(account_id))
    for row in ctx.db.scalars(intent_stmt.limit(8)):
        signals.append({"kind": "intent", "title": row.topic, "intensity": row.intensity, "source": row.source, "is_mock": row.is_mock})
    trigger_stmt = select(TriggerEvent).where(TriggerEvent.tenant_id == ctx.tenant_id, TriggerEvent.deleted_at.is_(None))
    if account_id:
        trigger_stmt = trigger_stmt.where(TriggerEvent.account_id == UUID(account_id))
    for row in ctx.db.scalars(trigger_stmt.limit(8)):
        signals.append({"kind": "trigger", "title": row.title, "source": row.source, "is_mock": row.is_mock})
    return {"signals": signals}


def tool_list_markets(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.market import Market

    rows = ctx.db.scalars(select(Market).where(Market.tenant_id == ctx.tenant_id, Market.deleted_at.is_(None))).all()
    return {
        "markets": [
            {
                "id": str(row.id),
                "name": row.name,
                "industry": row.industry,
                "attractiveness": row.attractiveness,
                "buying_timing": row.buying_timing,
                "reasons": row.score_reasons,
            }
            for row in rows[:10]
        ]
    }


def tool_list_campaigns(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.lifecycle import Campaign

    rows = ctx.db.scalars(select(Campaign).where(Campaign.tenant_id == ctx.tenant_id, Campaign.deleted_at.is_(None))).all()
    return {
        "campaigns": [
            {"id": str(row.id), "name": row.name, "channel": row.channel, "status": row.status, "budget": str(row.budget)}
            for row in rows[:10]
        ]
    }


def tool_list_deal_insights(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.lifecycle import DealInsight

    rows = ctx.db.scalars(
        select(DealInsight).where(DealInsight.tenant_id == ctx.tenant_id, DealInsight.deleted_at.is_(None))
    ).all()
    return {
        "insights": [
            {"opportunity_id": str(row.opportunity_id), "risk_score": row.risk_score, "reasons": row.reasons, "version": row.version}
            for row in rows[:10]
        ]
    }


def tool_get_autonomous_run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    run = get_owned(ctx.db, AutonomousRun, ctx.tenant_id, UUID(args["run_id"]))
    steps = ctx.db.scalars(
        select(AutonomousRunStep)
        .where(AutonomousRunStep.run_id == run.id, AutonomousRunStep.deleted_at.is_(None))
        .order_by(AutonomousRunStep.position.asc())
    ).all()
    return {
        "id": str(run.id),
        "status": run.status,
        "summary": run.summary,
        "trigger": run.trigger,
        "steps": [{"name": step.name, "status": step.status, "detail_json": step.detail_json} for step in steps],
        "note": "Explain this persisted run. Do not invent scores or spend.",
    }


def tool_extract_meeting_notes(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    row = extract_meeting_notes(
        ctx.db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.actor_id,
        transcript=str(args.get("transcript") or ""),
        title=str(args.get("title") or "Extracted meeting notes"),
        account_id=UUID(args["account_id"]) if args.get("account_id") else None,
        opportunity_id=UUID(args["opportunity_id"]) if args.get("opportunity_id") else None,
    )
    return {
        "id": str(row.id),
        "title": row.title,
        "summary": row.summary,
        "next_steps": row.next_steps,
        "provider": row.provider,
        "is_mock": row.is_mock,
    }


def tool_list_quotes(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.lifecycle import Quote

    rows = ctx.db.scalars(select(Quote).where(Quote.tenant_id == ctx.tenant_id, Quote.deleted_at.is_(None))).all()
    return {
        "quotes": [
            {
                "id": str(row.id),
                "opportunity_id": str(row.opportunity_id),
                "total": str(row.total),
                "discount_pct": row.discount_pct,
                "approval_required": row.approval_required,
            }
            for row in rows[:10]
        ]
    }


def tool_list_contacts(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    account_id = UUID(args["account_id"])
    get_owned(ctx.db, Account, ctx.tenant_id, account_id)
    rows = ctx.db.scalars(
        select(Contact).where(
            Contact.tenant_id == ctx.tenant_id,
            Contact.account_id == account_id,
            Contact.deleted_at.is_(None),
        )
    ).all()
    return {
        "contacts": [
            {
                "id": str(row.id),
                "name": f"{row.first_name} {row.last_name}",
                "title": row.title,
                "buying_role": row.buying_role,
            }
            for row in rows
        ]
    }


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "get_account": ToolSpec("get_account", "Get one account", "accounts.read", 0, tool_get_account),
    "search_accounts": ToolSpec("search_accounts", "Search accounts", "accounts.read", 0, tool_search_accounts),
    "get_lead": ToolSpec("get_lead", "Get one lead", "leads.read", 0, tool_get_lead),
    "get_opportunity": ToolSpec(
        "get_opportunity", "Get one opportunity", "opportunities.read", 0, tool_get_opportunity
    ),
    "get_customer": ToolSpec("get_customer", "Get one customer", "accounts.read", 0, tool_get_customer),
    "retrieve_knowledge": ToolSpec(
        "retrieve_knowledge", "Retrieve tenant knowledge", "knowledge.read", 0, tool_retrieve_knowledge
    ),
    "create_note": ToolSpec("create_note", "Create internal note", "tasks.write", 1, tool_create_note),
    "list_contacts": ToolSpec("list_contacts", "List account contacts", "contacts.read", 0, tool_list_contacts),
    "list_signals": ToolSpec("list_signals", "List tenant signals and triggers", "signals.read", 0, tool_list_signals),
    "list_markets": ToolSpec("list_markets", "List scored markets", "markets.read", 0, tool_list_markets),
    "list_campaigns": ToolSpec("list_campaigns", "List campaigns", "campaigns.read", 0, tool_list_campaigns),
    "list_deal_insights": ToolSpec("list_deal_insights", "List deal risk flags", "deals.read", 0, tool_list_deal_insights),
    "list_quotes": ToolSpec("list_quotes", "List quotes", "commercial.read", 0, tool_list_quotes),
    "get_autonomous_run": ToolSpec(
        "get_autonomous_run", "Explain a persisted Autopilot run", "autonomy.read", 0, tool_get_autonomous_run
    ),
    "extract_meeting_notes": ToolSpec(
        "extract_meeting_notes", "Extract notes from a transcript", "meetings.write", 1, tool_extract_meeting_notes
    ),
}


def run_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return {"error": f"Unknown tool {name}"}
    if spec.required_permission not in ctx.permissions:
        return {"error": "forbidden"}
    result = spec.handler(ctx, args)
    return json.loads(json.dumps(result, default=str))
