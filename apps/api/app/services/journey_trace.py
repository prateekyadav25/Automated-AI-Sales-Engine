from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AgentRun, AIApproval, ToolCall
from app.models.autonomy import AutonomousRun, AutonomousRunStep, EntityAutomationState
from app.models.crm import Activity, Lead, LeadScore
from app.models.identity import DomainEvent
from app.models.integrations import ProviderAction
from app.models.lifecycle import MeetingRecord


def full_trace(db: Session, *, tenant_id: UUID, entity_type: str, entity_id: str) -> dict:
    state = db.scalar(
        select(EntityAutomationState).where(
            EntityAutomationState.tenant_id == tenant_id,
            EntityAutomationState.entity_type == entity_type,
            EntityAutomationState.entity_id == entity_id,
            EntityAutomationState.deleted_at.is_(None),
        )
    )
    events = db.scalars(
        select(DomainEvent)
        .where(DomainEvent.tenant_id == tenant_id, DomainEvent.entity_type == entity_type, DomainEvent.entity_id == entity_id)
        .order_by(DomainEvent.created_at.asc())
    ).all()
    activities = db.scalars(
        select(Activity)
        .where(Activity.tenant_id == tenant_id, Activity.entity_type == entity_type, Activity.entity_id == entity_id, Activity.deleted_at.is_(None))
        .order_by(Activity.created_at.asc())
    ).all()
    approvals = db.scalars(
        select(AIApproval)
        .where(AIApproval.tenant_id == tenant_id, AIApproval.entity_type == entity_type, AIApproval.entity_id == entity_id, AIApproval.deleted_at.is_(None))
        .order_by(AIApproval.created_at.asc())
    ).all()
    actions = db.scalars(
        select(ProviderAction)
        .where(ProviderAction.tenant_id == tenant_id, ProviderAction.entity_type == entity_type, ProviderAction.entity_id == entity_id, ProviderAction.deleted_at.is_(None))
        .order_by(ProviderAction.created_at.asc())
    ).all()
    runs = []
    if state and state.run_id:
        run = db.get(AutonomousRun, state.run_id)
        steps = db.scalars(select(AutonomousRunStep).where(AutonomousRunStep.run_id == state.run_id).order_by(AutonomousRunStep.position.asc())).all()
        if run:
            runs.append(
                {
                    "id": str(run.id),
                    "status": run.status,
                    "workflow": run.workflow,
                    "steps": [{"name": step.name, "status": step.status, "detail": step.detail_json} for step in steps],
                }
            )
    score = None
    why = ""
    if entity_type == "lead":
        lead = db.get(Lead, UUID(entity_id)) if entity_id else None
        if lead:
            why = f"source={lead.source}; status={lead.status}"
            latest = db.scalar(select(LeadScore).where(LeadScore.lead_id == lead.id).order_by(LeadScore.created_at.desc()))
            if latest:
                score = {"total": latest.total, "version": latest.version, "reasons": latest.reasons}
    meetings = db.scalars(
        select(MeetingRecord).where(
            MeetingRecord.tenant_id == tenant_id,
            MeetingRecord.deleted_at.is_(None),
            MeetingRecord.lead_id == UUID(entity_id) if entity_type == "lead" else MeetingRecord.lead_id.is_(None),
        )
    ).all() if entity_type == "lead" else []
    tools = []
    agents = db.scalars(select(AgentRun).where(AgentRun.tenant_id == tenant_id).order_by(AgentRun.created_at.desc()).limit(8)).all()
    for agent in agents:
        calls = db.scalars(select(ToolCall).where(ToolCall.run_id == agent.id)).all()
        tools.extend({"agent": agent.agent, "tool": call.tool_name, "ok": call.success} for call in calls)
    return {
        "why_selected": why or (state.last_action if state else ""),
        "evidence": [event.event_type for event in events[-12:]],
        "score": score,
        "rule": score["version"] if score else "rules-v1",
        "agent": runs[0]["workflow"] if runs else "",
        "tools": tools[:12],
        "approvals": [
            {
                "id": str(row.id),
                "action": row.action_type,
                "status": row.status,
                "decided_by": str(row.decided_by) if row.decided_by else None,
            }
            for row in approvals
        ],
        "providers": [
            {
                "provider": row.provider,
                "mode": row.provider_mode,
                "status": row.status,
                "policy_version": row.policy_version,
                "external_id": row.external_id,
            }
            for row in actions
        ],
        "afterward": [row.title for row in activities[-8:]],
        "meetings": [str(row.id) for row in meetings],
        "state": state.state if state else "NONE",
        "runs": runs,
    }
