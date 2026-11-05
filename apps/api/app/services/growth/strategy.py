"""The client-approved strategy automation may follow.

A strategy names pillars backed by approved facts, the accounts, their cadence
and formats, the call to action, and whether creation and scheduling may run
without a person. Editing an approved strategy creates a new draft version. The
approved version stays in force until the draft is approved.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.funnel import PublicFormKey
from app.models.growth import GrowthAccount, GrowthBusinessEvent, GrowthStrategy
from app.services.audit import emit_event, write_audit
from app.services.growth.brand import approved_facts, ensure_profile
from app.services.growth.common import PLATFORM_FORMATS, digest, dumps, iso, loads, now, parse_uuid

METRICS = ("reach", "engagement", "link_clicks", "enquiries")
_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
DEFAULT_REVIEW_TERMS = ["guarantee", "cure", "risk-free", "best", "#1", "number one", "free", "discount", "price"]


def latest_strategy(db: Session, tenant_id: UUID) -> GrowthStrategy | None:
    return db.scalar(
        select(GrowthStrategy)
        .where(GrowthStrategy.tenant_id == tenant_id, GrowthStrategy.deleted_at.is_(None), GrowthStrategy.status != "superseded")
        .order_by(GrowthStrategy.version.desc())
    )


def active_strategy(db: Session, tenant_id: UUID) -> GrowthStrategy | None:
    return db.scalar(
        select(GrowthStrategy)
        .where(GrowthStrategy.tenant_id == tenant_id, GrowthStrategy.deleted_at.is_(None), GrowthStrategy.status.in_(["approved", "paused"]))
        .order_by(GrowthStrategy.version.desc())
    )


def owned_strategy(db: Session, tenant_id: UUID, strategy_id: UUID) -> GrowthStrategy:
    row = db.scalar(select(GrowthStrategy).where(GrowthStrategy.tenant_id == tenant_id, GrowthStrategy.id == strategy_id, GrowthStrategy.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return row


def suggest_pillars(db: Session, tenant_id: UUID) -> list[dict]:
    """Pillars drawn only from approved facts. A category without approved facts gets no pillar."""
    facts = approved_facts(db, tenant_id)
    groups = (
        ("offer", "What we offer", "Products and services the site states.", ("product", "service")),
        ("proof", "Proof", "Approved claims, quoted as written.", ("claim",)),
        ("company", "Who we are", "The company description and where it works.", ("description", "location", "company_name")),
    )
    pillars: list[dict] = []
    for key, name, description, categories in groups:
        ids = [str(fact.id) for fact in facts if fact.category in categories]
        if ids:
            pillars.append({"key": key, "name": name, "description": description, "fact_ids": ids[:12]})
    for fact in [fact for fact in facts if fact.category == "theme"][:3]:
        slug = re.sub(r"[^a-z0-9]+", "-", fact.statement.casefold()).strip("-")[:30] or "theme"
        pillars.append({"key": f"theme-{slug}", "name": fact.statement[:60], "description": "A recurring theme from the site or past captions.", "fact_ids": [str(fact.id)]})
    return pillars


def _validate(db: Session, tenant_id: UUID, payload: dict) -> dict:
    facts = {str(fact.id): fact for fact in approved_facts(db, tenant_id)}
    pillars_in = payload.get("pillars") or []
    if not 1 <= len(pillars_in) <= 8:
        raise HTTPException(status_code=422, detail="A strategy needs between one and eight pillars.")
    pillars: list[dict] = []
    for pillar in pillars_in:
        key = str(pillar.get("key") or "").strip().lower()
        name = str(pillar.get("name") or "").strip()
        ids = [str(item) for item in pillar.get("fact_ids") or []]
        if not _KEY.match(key) or not name:
            raise HTTPException(status_code=422, detail="Each pillar needs a short key and a name.")
        unknown = [item for item in ids if item not in facts]
        if unknown or not ids:
            raise HTTPException(status_code=422, detail=f"Pillar {name} must cite approved facts only. Approve the facts first.")
        if any(item["key"] == key for item in pillars):
            raise HTTPException(status_code=422, detail="Pillar keys must be unique.")
        pillars.append({"key": key, "name": name[:80], "description": str(pillar.get("description") or "")[:400], "fact_ids": ids})
    cadence_in = payload.get("cadence") or {}
    if not isinstance(cadence_in, dict) or not cadence_in:
        raise HTTPException(status_code=422, detail="Choose at least one account and its weekly cadence.")
    cadence: dict[str, dict] = {}
    for raw_id, plan in cadence_in.items():
        account_id = parse_uuid(raw_id)
        account = db.get(GrowthAccount, account_id) if account_id else None
        if account is None or account.tenant_id != tenant_id or account.deleted_at is not None or account.status in {"disconnected", "revoked"}:
            raise HTTPException(status_code=422, detail="The cadence names an account that is not connected in this workspace.")
        try:
            formats = {str(name): int(count) for name, count in (plan.get("formats") or {}).items() if int(count) > 0}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Format counts must be whole numbers.") from exc
        unsupported = [name for name in formats if name not in PLATFORM_FORMATS[account.platform]]
        if unsupported:
            raise HTTPException(status_code=422, detail=f"{account.platform.title()} does not support {', '.join(unsupported)} in this engine.")
        per_week = sum(formats.values())
        if not 1 <= per_week <= 14:
            raise HTTPException(status_code=422, detail="Each account needs between one and fourteen posts a week.")
        cadence[str(account.id)] = {"posts_per_week": per_week, "formats": formats}
    metric = str(payload.get("optimization_metric") or "reach")
    if metric not in METRICS:
        raise HTTPException(status_code=422, detail=f"Optimization metric must be one of {', '.join(METRICS)}.")
    kind = str(payload.get("destination_kind") or "form")
    form_id = parse_uuid(payload.get("destination_form_key_id"))
    url = str(payload.get("destination_url") or "").strip()
    if kind == "form":
        form = db.get(PublicFormKey, form_id) if form_id else None
        if form is None or form.tenant_id != tenant_id or form.status != "active" or form.deleted_at is not None:
            raise HTTPException(status_code=422, detail="Choose an active enquiry form for the call to action.")
    elif kind == "website":
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise HTTPException(status_code=422, detail="The website destination must be an https address.")
        form_id = None
    else:
        raise HTTPException(status_code=422, detail="Destination must be form or website.")
    horizon = int(payload.get("horizon_days") or 30)
    if not 7 <= horizon <= 30:
        raise HTTPException(status_code=422, detail="The rolling horizon must be between 7 and 30 days.")
    terms = [str(term).strip().casefold() for term in payload.get("review_terms") or DEFAULT_REVIEW_TERMS if str(term).strip()]
    audiences = [str(item).strip()[:200] for item in payload.get("audiences") or [] if str(item).strip()]
    return {
        "objective": str(payload.get("objective") or "").strip()[:1000],
        "optimization_metric": metric,
        "pillars": pillars,
        "audiences": audiences[:6],
        "cadence": cadence,
        "call_to_action": str(payload.get("call_to_action") or "").strip()[:300],
        "destination_kind": kind,
        "destination_form_key_id": str(form_id) if form_id else "",
        "destination_url": url if kind == "website" else "",
        "auto_create": bool(payload.get("auto_create", True)),
        "auto_schedule": bool(payload.get("auto_schedule", False)),
        "review_terms": sorted(set(terms))[:40],
        "horizon_days": horizon,
    }


def save_strategy(db: Session, *, tenant_id: UUID, actor_id: UUID, payload: dict) -> GrowthStrategy:
    clean = _validate(db, tenant_id, payload)
    if not clean["call_to_action"]:
        raise HTTPException(status_code=422, detail="State the intended call to action.")
    latest = latest_strategy(db, tenant_id)
    if latest is not None and latest.status == "draft":
        row = latest
    else:
        version = int(
            db.scalar(select(GrowthStrategy.version).where(GrowthStrategy.tenant_id == tenant_id).order_by(GrowthStrategy.version.desc()).limit(1))
            or 0
        ) + 1
        row = GrowthStrategy(tenant_id=tenant_id, created_by=actor_id, version=version, status="draft")
        db.add(row)
    profile = ensure_profile(db, tenant_id, actor_id)
    row.operating_plan_id = profile.operating_plan_id
    row.objective = clean["objective"]
    row.optimization_metric = clean["optimization_metric"]
    row.pillars_json = dumps(clean["pillars"])
    row.audiences_json = dumps(clean["audiences"])
    row.cadence_json = dumps(clean["cadence"])
    row.call_to_action = clean["call_to_action"]
    row.destination_kind = clean["destination_kind"]
    row.destination_form_key_id = parse_uuid(clean["destination_form_key_id"])
    row.destination_url = clean["destination_url"]
    row.auto_create = clean["auto_create"]
    row.auto_schedule = clean["auto_schedule"]
    row.review_terms_json = dumps(clean["review_terms"])
    row.horizon_days = clean["horizon_days"]
    row.content_hash = digest(dumps(clean))
    row.updated_by = actor_id
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.strategy_save", entity_type="growth_strategy", entity_id=str(row.id), after={"version": row.version, "content_hash": row.content_hash})
    return row


def approve_strategy(db: Session, *, tenant_id: UUID, actor_id: UUID, strategy_id: UUID) -> GrowthStrategy:
    row = owned_strategy(db, tenant_id, strategy_id)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail=f"Version {row.version} is {row.status}. Only a draft can be approved.")
    payload = {
        "objective": row.objective,
        "optimization_metric": row.optimization_metric,
        "pillars": loads(row.pillars_json, []),
        "audiences": loads(row.audiences_json, []),
        "cadence": loads(row.cadence_json, {}),
        "call_to_action": row.call_to_action,
        "destination_kind": row.destination_kind,
        "destination_form_key_id": str(row.destination_form_key_id or ""),
        "destination_url": row.destination_url,
        "auto_create": row.auto_create,
        "auto_schedule": row.auto_schedule,
        "review_terms": loads(row.review_terms_json, []),
        "horizon_days": row.horizon_days,
    }
    clean = _validate(db, tenant_id, payload)
    if digest(dumps(clean)) != row.content_hash:
        raise HTTPException(status_code=409, detail="Facts or accounts changed since this draft was saved. Save the draft again and review it.")
    previous = active_strategy(db, tenant_id)
    if previous is not None and previous.id != row.id:
        previous.status = "superseded"
    row.status = "approved"
    row.approved_by = actor_id
    row.approved_at = now()
    db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="growth.strategy_approve",
        entity_type="growth_strategy",
        entity_id=str(row.id),
        before={"previous": str(previous.id) if previous is not None else ""},
        after={"version": row.version, "auto_create": row.auto_create, "auto_schedule": row.auto_schedule},
    )
    emit_event(db, tenant_id=tenant_id, event_type="social_growth.strategy_approved", entity_type="growth_strategy", entity_id=str(row.id), payload={"version": row.version})
    return row


def set_strategy_paused(db: Session, *, tenant_id: UUID, actor_id: UUID, paused: bool) -> GrowthStrategy:
    row = active_strategy(db, tenant_id)
    if row is None:
        raise HTTPException(status_code=409, detail="There is no approved strategy.")
    before = row.status
    row.status = "paused" if paused else "approved"
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.strategy_pause" if paused else "growth.strategy_resume", entity_type="growth_strategy", entity_id=str(row.id), before={"status": before}, after={"status": row.status})
    return row


def strategy_out(row: GrowthStrategy | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "version": row.version,
        "status": row.status,
        "objective": row.objective,
        "optimization_metric": row.optimization_metric,
        "pillars": loads(row.pillars_json, []),
        "audiences": loads(row.audiences_json, []),
        "cadence": loads(row.cadence_json, {}),
        "call_to_action": row.call_to_action,
        "destination_kind": row.destination_kind,
        "destination_form_key_id": str(row.destination_form_key_id or ""),
        "destination_url": row.destination_url,
        "auto_create": row.auto_create,
        "auto_schedule": row.auto_schedule,
        "review_terms": loads(row.review_terms_json, []),
        "horizon_days": row.horizon_days,
        "approved_at": iso(row.approved_at),
        "content_hash": row.content_hash,
    }


def save_event(db: Session, *, tenant_id: UUID, actor_id: UUID, title: str, kind: str, starts_on: str, ends_on: str, details: str, fact_ids: list[str], source_url: str) -> GrowthBusinessEvent:
    if not title.strip():
        raise HTTPException(status_code=422, detail="An event needs a title.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", starts_on or "") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ends_on or "") or ends_on < starts_on:
        raise HTTPException(status_code=422, detail="Event dates must be YYYY-MM-DD and end on or after the start.")
    approved = {str(fact.id) for fact in approved_facts(db, tenant_id)}
    unknown = [item for item in fact_ids if item not in approved]
    if unknown:
        raise HTTPException(status_code=422, detail="An event can cite approved facts only.")
    row = GrowthBusinessEvent(
        tenant_id=tenant_id,
        created_by=actor_id,
        title=title.strip()[:200],
        kind=(kind or "event").strip()[:32],
        starts_on=starts_on,
        ends_on=ends_on,
        details=details.strip()[:2000],
        fact_ids=dumps(fact_ids),
        source_url=source_url.strip()[:1000],
    )
    db.add(row)
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.event_save", entity_type="growth_business_event", entity_id=str(row.id), after={"title": row.title, "starts_on": starts_on, "ends_on": ends_on})
    return row


def event_out(row: GrowthBusinessEvent) -> dict:
    return {
        "id": str(row.id),
        "title": row.title,
        "kind": row.kind,
        "starts_on": row.starts_on,
        "ends_on": row.ends_on,
        "details": row.details,
        "fact_ids": loads(row.fact_ids, []),
        "source_url": row.source_url,
        "status": row.status,
    }
