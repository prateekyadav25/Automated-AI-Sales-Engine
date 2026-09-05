import json

from app.models.ai import AIApproval
from app.schemas.ai import ApprovalOut


def approval_out(row: AIApproval) -> ApprovalOut:
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    who = str(payload.get("lead_id") or payload.get("campaign_id") or row.entity_id or "")
    message = str(payload.get("body") or payload.get("template") or "")
    return ApprovalOut(
        id=row.id,
        action_level=row.action_level,
        action_type=row.action_type,
        title=row.title,
        payload_json=row.payload_json,
        status=row.status,
        decision_note=row.decision_note,
        run_id=row.run_id,
        entity_type=row.entity_type or str(payload.get("entity_type") or ""),
        entity_id=row.entity_id or str(payload.get("lead_id") or payload.get("campaign_id") or ""),
        who=who,
        why=str(payload.get("why") or "Autopilot prepared a governed action."),
        evidence=str(payload.get("evidence") or ""),
        risk=str(payload.get("risk") or "External or commercial action requires a human gate."),
        expected_outcome=str(payload.get("expected_outcome") or ""),
        message=message,
        commercial_impact=str(payload.get("commercial_impact") or ""),
        budget_impact=str(payload.get("budget") or payload.get("budget_impact") or ""),
    )
