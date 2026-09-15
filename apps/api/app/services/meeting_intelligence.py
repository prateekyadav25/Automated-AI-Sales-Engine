from __future__ import annotations

import json
import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.providers import get_llm_provider
from app.models.crm import Opportunity
from app.models.lifecycle import MeetingRecord
from app.services.audit import emit_event
from app.services.crm import add_activity
from app.services.nba import generate_for_opportunity
from app.services.query import get_owned


def _only_from_transcript(text: str, transcript: str) -> str:
    if not text or not transcript:
        return ""
    lowered = transcript.lower()
    if text.lower() in lowered:
        return text.strip()
    words = [word for word in re.findall(r"[a-zA-Z0-9']+", text.lower()) if len(word) > 3]
    if words and sum(1 for word in words if word in lowered) >= max(1, len(words) // 2):
        return text.strip()
    return ""


def extract_insights(
    *,
    transcript: str,
    participants: list[str] | None = None,
    db: Session | None = None,
    tenant_id: UUID | None = None,
) -> dict:
    _ = participants
    text = transcript.strip()
    if not text:
        return {
            "summary": "",
            "commitments": [],
            "objections": [],
            "risks": [],
            "next_actions": [],
            "abstained": True,
            "reason": "No transcript evidence.",
        }
    llm = get_llm_provider(db, tenant_id)
    completion = llm.complete(
        (
            "Untrusted transcript:\n"
            f"{text}\n\n"
            "Return JSON with keys summary, commitments, objections, risks, next_actions. "
            "Use only statements present in the transcript. If a field cannot be cited, use an empty list or empty string. Never invent numbers."
        ),
        system="You extract meeting evidence. Abstain rather than invent. Output JSON only.",
    )
    payload: dict = {}
    try:
        start = completion.text.find("{")
        end = completion.text.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(completion.text[start : end + 1])
            if isinstance(parsed, dict):
                payload = parsed
    except json.JSONDecodeError:
        payload = {}
    summary = _only_from_transcript(str(payload.get("summary") or ""), text) or (
        "" if completion.is_mock else _only_from_transcript(completion.text[:800], text)
    )
    if not summary:
        summary = "Insufficient transcript evidence to summarize."

    def _list(key: str) -> list[str]:
        raw = payload.get(key) or []
        items = raw if isinstance(raw, list) else [raw]
        kept = []
        for item in items:
            cited = _only_from_transcript(str(item), text)
            if cited:
                kept.append(cited)
        return kept

    return {
        "summary": summary[:4000],
        "commitments": _list("commitments"),
        "objections": _list("objections"),
        "risks": _list("risks"),
        "next_actions": _list("next_actions"),
        "abstained": not _list("next_actions") and summary.startswith("Insufficient"),
        "reason": "" if not completion.is_mock else "LLM is mock; only transcript-cited phrases are kept.",
        "provider": completion.provider,
        "is_mock": completion.is_mock,
    }


def apply_meeting_insights(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    meeting: MeetingRecord,
    insights: dict,
) -> MeetingRecord:
    meeting.insights_json = json.dumps(insights)
    if insights.get("summary"):
        meeting.summary = str(insights["summary"])[:4000]
    actions = insights.get("next_actions") or []
    if actions:
        meeting.next_steps = str(actions[0])[:500]
    if meeting.opportunity_id and actions:
        opportunity = get_owned(db, Opportunity, tenant_id, meeting.opportunity_id)
        if not opportunity.next_step:
            opportunity.next_step = str(actions[0])[:255]
        generate_for_opportunity(db, tenant_id, opportunity, actor_id)
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="meeting",
        entity_id=str(meeting.id),
        activity_type="meeting",
        title="Meeting insights extracted",
        body=str(insights.get("summary") or ""),
        actor_type="ai",
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="meeting.insights",
        entity_type="meeting",
        entity_id=str(meeting.id),
        payload={"abstained": bool(insights.get("abstained")), "next_actions": insights.get("next_actions") or []},
    )
    return meeting
