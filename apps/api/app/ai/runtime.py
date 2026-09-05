import json
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.ai.rag import retrieve
from app.ai.tools import ToolContext, run_tool
from app.models.ai import (
    AgentRun,
    AIApproval,
    AIConversation,
    AIMessage,
    AIRecommendation,
    ModelUsage,
    Prompt,
    ToolCall,
)
from app.models.crm import Account, Lead, Opportunity
from app.models.identity import FeatureFlag
from app.services.query import get_owned


def _prompt(db: Session, tenant_id: UUID, key: str, fallback: str) -> tuple[str, str]:
    row = db.scalar(
        select(Prompt).where(
            Prompt.tenant_id == tenant_id,
            Prompt.prompt_key == key,
            Prompt.deleted_at.is_(None),
            Prompt.status == "approved",
        )
    )
    if row:
        return row.template, row.version
    return fallback, "inline-fallback"


def _log_usage(db: Session, tenant_id: UUID, agent: str, prompt_version: str, result) -> None:
    db.add(
        ModelUsage(
            tenant_id=tenant_id,
            provider=result.provider,
            model=result.model,
            agent=agent,
            prompt_version=prompt_version,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            estimated_cost=result.estimated_cost,
            is_mock=result.is_mock,
        )
    )


def _flag_enabled(db: Session, tenant_id: UUID, key: str) -> bool:
    row = db.scalar(
        select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id, FeatureFlag.key == key)
    )
    return bool(row and row.enabled)


def route_intent(message: str) -> str:
    text = message.lower()
    if any(word in text for word in ("churn", "renew", "health")):
        return "customer"
    if "draft" in text and "email" in text:
        return "draft_email"
    if "research" in text or "account" in text and "summar" in text:
        return "research_account"
    if "lead" in text:
        return "summarize_lead"
    if "opportunit" in text or "deal" in text or "pipeline" in text:
        return "summarize_opportunity"
    if "knowledge" in text or "playbook" in text:
        return "knowledge"
    return "general"


def _extract_uuid(message: str) -> str | None:
    match = re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        message,
    )
    return match.group(0) if match else None


def _extract_name(message: str) -> str:
    match = re.search(r"(?:account|company|lead|deal)\s+([A-Za-z0-9&.\- ]{2,60})", message, re.I)
    return match.group(1).strip() if match else ""


def run_copilot(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    permissions: set[str],
    message: str,
    conversation_id: UUID | None,
    correlation_id: str = "",
) -> dict:
    if conversation_id:
        conversation = get_owned(db, AIConversation, tenant_id, conversation_id)
    else:
        conversation = AIConversation(tenant_id=tenant_id, created_by=actor_id, title=message[:80])
        db.add(conversation)
        db.flush()
    db.add(AIMessage(conversation_id=conversation.id, role="user", content=message))

    intent = route_intent(message)
    run = AgentRun(
        tenant_id=tenant_id,
        created_by=actor_id,
        agent="supervisor",
        status="running",
        input_json=json.dumps({"message": message, "intent": intent}),
        correlation_id=correlation_id,
    )
    db.add(run)
    db.flush()
    ctx = ToolContext(db=db, tenant_id=tenant_id, actor_id=actor_id, permissions=permissions)
    observations: list[dict] = []

    if intent == "research_account":
        extracted = _extract_uuid(message)
        if extracted:
            observations.append(run_tool(ctx, "get_account", {"account_id": extracted}))
            observations.append(run_tool(ctx, "list_contacts", {"account_id": extracted}))
        else:
            observations.append(run_tool(ctx, "search_accounts", {"q": _extract_name(message) or message}))
        observations.append(run_tool(ctx, "retrieve_knowledge", {"query": message}))
        agent = "account_research"
        system_key = "account_research"
        fallback = "You are AccountResearchAgent. Use only tool observations. Cite knowledge chunk ids. Do not invent facts."
    elif intent == "summarize_lead":
        extracted = _extract_uuid(message)
        if extracted:
            observations.append(run_tool(ctx, "get_lead", {"lead_id": extracted}))
        observations.append(run_tool(ctx, "retrieve_knowledge", {"query": message}))
        agent = "lead_summary"
        system_key = "lead_summary"
        fallback = "You are summarizing a lead using tools only. Explain scores if present. Do not invent numbers."
    elif intent == "summarize_opportunity":
        extracted = _extract_uuid(message)
        if extracted:
            observations.append(run_tool(ctx, "get_opportunity", {"opportunity_id": extracted}))
        agent = "opportunity_summary"
        system_key = "opportunity_summary"
        fallback = "Summarize the opportunity from tools. Do not change commercial terms."
    elif intent == "draft_email":
        extracted = _extract_uuid(message)
        if extracted:
            observations.append(run_tool(ctx, "get_lead", {"lead_id": extracted}))
        agent = "email_draft"
        system_key = "email_draft"
        fallback = "Draft an email. Do not send. Respect opt-out if present."
    elif intent == "knowledge":
        observations.append(run_tool(ctx, "retrieve_knowledge", {"query": message}))
        agent = "knowledge"
        system_key = "knowledge"
        fallback = "Answer from retrieved chunks only. If none, abstain."
    else:
        observations.append(run_tool(ctx, "search_accounts", {"q": _extract_name(message) or message}))
        observations.append(run_tool(ctx, "retrieve_knowledge", {"query": message}))
        agent = "supervisor"
        system_key = "copilot"
        fallback = "You are the AGRAYIAN copilot. Use observations. Never claim live integrations that were not used."

    db.add(
        ToolCall(
            run_id=run.id,
            tool_name="bundle",
            input_json=json.dumps({"intent": intent}),
            output_json=json.dumps(observations, default=str),
            success=True,
        )
    )
    system, version = _prompt(db, tenant_id, system_key, fallback)
    prompt = f"User message:\n{message}\n\nTool observations:\n{json.dumps(observations, default=str)[:8000]}"
    llm = get_llm_provider()
    result = llm.complete(prompt, system=system)
    _log_usage(db, tenant_id, agent, version, result)
    citations = []
    for item in observations:
        hits = item.get("hits") if isinstance(item, dict) else None
        if hits:
            citations.extend(hits)

    approval_id = None
    if intent == "draft_email" and ("send" in message.lower() or "email them" in message.lower()):
        approval = AIApproval(
            tenant_id=tenant_id,
            created_by=actor_id,
            action_level=2,
            action_type="email.send",
            title="Send drafted email",
            payload_json=json.dumps({"body": result.text, "message": message}),
            status="pending",
        )
        db.add(approval)
        db.flush()
        approval_id = approval.id

    db.add(
        AIMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=result.text,
            citations_json=json.dumps(citations, default=str),
        )
    )
    run.status = "completed"
    run.output_json = json.dumps({"reply": result.text, "intent": intent})
    db.commit()
    return {
        "conversation_id": conversation.id,
        "reply": result.text,
        "citations": citations,
        "provider": result.provider,
        "is_mock": result.is_mock,
        "approval_id": approval_id,
    }


def research_account(
    db: Session, *, tenant_id: UUID, actor_id: UUID, permissions: set[str], account_id: UUID
) -> dict:
    ctx = ToolContext(db=db, tenant_id=tenant_id, actor_id=actor_id, permissions=permissions)
    account = run_tool(ctx, "get_account", {"account_id": str(account_id)})
    contacts = run_tool(ctx, "list_contacts", {"account_id": str(account_id)})
    knowledge = run_tool(ctx, "retrieve_knowledge", {"query": account.get("name", "") if isinstance(account, dict) else ""})
    system, version = _prompt(
        db,
        tenant_id,
        "account_research",
        "Produce an account research brief from tools only. Do not invent financials.",
    )
    llm = get_llm_provider()
    result = llm.complete(
        json.dumps({"account": account, "contacts": contacts, "knowledge": knowledge}, default=str),
        system=system,
    )
    _log_usage(db, tenant_id, "account_research", version, result)
    structured = {
        "brief": result.text,
        "sources": ["tool:get_account", "tool:list_contacts", "tool:retrieve_knowledge"],
        "evidence": "Tool-grounded observations only. Financials were not invented.",
        "confidence": 50 if result.is_mock else 70,
        "conversation_angle": "Confirm the problem and buying process from cited tools.",
        "known_risks": "Do not treat mock or missing data as a budget or close date.",
        "relevant_solution": "",
        "provider": result.provider,
        "is_mock": result.is_mock,
    }
    rec = AIRecommendation(
        tenant_id=tenant_id,
        created_by=actor_id,
        entity_type="account",
        entity_id=str(account_id),
        kind="research",
        title="Account research brief",
        body=json.dumps(structured, default=str),
        status="draft",
    )
    db.add(rec)
    db.flush()
    return {
        "brief": result.text,
        "provider": result.provider,
        "is_mock": result.is_mock,
        "account": account,
        "sources": structured["sources"],
        "confidence": structured["confidence"],
    }


def draft_email(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    permissions: set[str],
    entity_type: str,
    entity_id: UUID,
    intent: str,
    send: bool,
) -> dict:
    ctx = ToolContext(db=db, tenant_id=tenant_id, actor_id=actor_id, permissions=permissions)
    if entity_type == "lead":
        payload = run_tool(ctx, "get_lead", {"lead_id": str(entity_id)})
        if isinstance(payload, dict) and payload.get("opt_out"):
            body = "Suppressed: lead is opted out. No email drafted for send."
            rec = AIRecommendation(
                tenant_id=tenant_id,
                created_by=actor_id,
                entity_type=entity_type,
                entity_id=str(entity_id),
                kind="email_draft",
                title="Suppressed",
                body=body,
                status="blocked",
            )
            db.add(rec)
            db.commit()
            return {
                "recommendation_id": rec.id,
                "subject": "Suppressed",
                "body": body,
                "approval_id": None,
                "provider": "policy",
                "is_mock": True,
            }
    elif entity_type == "account":
        payload = run_tool(ctx, "get_account", {"account_id": str(entity_id)})
    elif entity_type == "opportunity":
        payload = run_tool(ctx, "get_opportunity", {"opportunity_id": str(entity_id)})
    else:
        payload = {"error": "unsupported entity"}
    system, version = _prompt(db, tenant_id, "email_draft", "Draft a professional email. Do not send.")
    llm = get_llm_provider()
    result = llm.complete(json.dumps({"intent": intent, "record": payload}, default=str), system=system)
    _log_usage(db, tenant_id, "email_draft", version, result)
    rec = AIRecommendation(
        tenant_id=tenant_id,
        created_by=actor_id,
        entity_type=entity_type,
        entity_id=str(entity_id),
        kind="email_draft",
        title=f"Email draft ({intent})",
        body=result.text,
        status="draft",
    )
    db.add(rec)
    db.flush()
    approval_id = None
    if send:
        if _flag_enabled(db, tenant_id, "ENABLE_AUTO_EMAIL"):
            approval = AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="email.send",
                title="Send email draft",
                payload_json=json.dumps({"recommendation_id": str(rec.id), "body": result.text}),
                status="pending",
            )
            db.add(approval)
            db.flush()
            approval_id = approval.id
        else:
            approval = AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="email.send",
                title="Send email draft (auto-send disabled)",
                payload_json=json.dumps({"recommendation_id": str(rec.id), "body": result.text}),
                status="pending",
            )
            db.add(approval)
            db.flush()
            approval_id = approval.id
    db.commit()
    subject = "Follow-up"
    if result.text.lower().startswith("subject:"):
        subject = result.text.split("\n", 1)[0].replace("Subject:", "").strip()
    return {
        "recommendation_id": rec.id,
        "subject": subject,
        "body": result.text,
        "approval_id": approval_id,
        "provider": result.provider,
        "is_mock": result.is_mock,
    }


def meeting_prep(
    db: Session, *, tenant_id: UUID, actor_id: UUID, permissions: set[str], account_id: UUID
) -> dict:
    ctx = ToolContext(db=db, tenant_id=tenant_id, actor_id=actor_id, permissions=permissions)
    account = run_tool(ctx, "get_account", {"account_id": str(account_id)})
    contacts = run_tool(ctx, "list_contacts", {"account_id": str(account_id)})
    knowledge = run_tool(ctx, "retrieve_knowledge", {"query": "discovery meeting playbook"})
    system, version = _prompt(
        db,
        tenant_id,
        "meeting_prep",
        "Prepare a meeting brief from tools only. Include agenda, risks, and questions. Do not invent quotes.",
    )
    llm = get_llm_provider()
    result = llm.complete(
        json.dumps({"account": account, "contacts": contacts, "knowledge": knowledge}, default=str),
        system=system,
    )
    _log_usage(db, tenant_id, "meeting_prep", version, result)
    rec = AIRecommendation(
        tenant_id=tenant_id,
        created_by=actor_id,
        entity_type="account",
        entity_id=str(account_id),
        kind="meeting_prep",
        title="Meeting preparation brief",
        body=result.text,
        status="draft",
    )
    db.add(rec)
    db.commit()
    return {"brief": result.text, "provider": result.provider, "is_mock": result.is_mock}


def summarize_entity(
    db: Session, *, tenant_id: UUID, actor_id: UUID, permissions: set[str], entity_type: str, entity_id: UUID
) -> dict:
    ctx = ToolContext(db=db, tenant_id=tenant_id, actor_id=actor_id, permissions=permissions)
    mapping = {
        "account": ("get_account", {"account_id": str(entity_id)}, "account_research"),
        "lead": ("get_lead", {"lead_id": str(entity_id)}, "lead_summary"),
        "opportunity": ("get_opportunity", {"opportunity_id": str(entity_id)}, "opportunity_summary"),
    }
    if entity_type not in mapping:
        return {"summary": "Unsupported entity", "is_mock": True, "provider": "none"}
    tool, args, key = mapping[entity_type]
    payload = run_tool(ctx, tool, args)
    hits = retrieve(db, tenant_id=tenant_id, query=json.dumps(payload, default=str)[:200])
    system, version = _prompt(db, tenant_id, key, "Summarize using tools and citations only.")
    llm = get_llm_provider()
    result = llm.complete(json.dumps({"record": payload, "knowledge": hits}, default=str), system=system)
    _log_usage(db, tenant_id, key, version, result)
    db.commit()
    return {"summary": result.text, "citations": hits, "provider": result.provider, "is_mock": result.is_mock}


# Keep model imports referenced for type checkers / future close-won summaries.
_ = (Account, Lead, Opportunity)
