"""Rolling calendar for every account in the approved strategy.

Slots fall inside each account's posting windows in its own time zone. Every
slot gets a brief that names the approved facts it may use, the recent posts
it was compared with, the evidence behind pillar weights, any business event,
and the call to action. Planning never publishes and never invents a metric.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.growth import (
    BrandFact,
    GrowthAccount,
    GrowthBusinessEvent,
    GrowthCalendarItem,
    GrowthCreative,
    GrowthMedia,
    GrowthMetricObservation,
    GrowthPublication,
    GrowthStrategy,
)
from app.services.audit import write_audit
from app.services.growth.brand import approved_facts
from app.services.growth.common import PLATFORM_FORMATS, aware, dumps, iso, loads, now
from app.services.growth.governance import withdraw_publish_requests
from app.services.growth.strategy import active_strategy

LEAD_MINUTES = 90
SIMILARITY_THRESHOLD = 0.55
PERFORMANCE_MINIMUM = 5
OPEN_STATUSES = ("planned", "creative_ready", "needs_review", "approved", "scheduled", "blocked")
PLATFORM_METRIC = {
    "reach": {"instagram": "reach", "facebook": "post_total_media_view_unique"},
    "engagement": {"instagram": "total_interactions", "facebook": "post_clicks"},
}


def _shingles(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    pairs = {f"{left} {right}" for left, right in zip(words, words[1:], strict=False)}
    return pairs or set(words)


def similarity(left: str, right: str) -> float:
    a, b = _shingles(left), _shingles(right)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 3)


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def week_template(windows: list[dict], per_week: int, daily_cap: int) -> list[tuple[int, int, int]]:
    allowed = sorted({int(day) for window in windows for day in window.get("days") or []})
    if not allowed or per_week <= 0:
        return []
    if per_week <= len(allowed):
        days = [allowed[(index * len(allowed)) // per_week] for index in range(per_week)]
    else:
        days = [allowed[index % len(allowed)] for index in range(per_week)]
    counts: dict[int, int] = {}
    for day in days:
        if counts.get(day, 0) < max(daily_cap, 1):
            counts[day] = counts.get(day, 0) + 1
    return [(day, index, total) for day, total in sorted(counts.items()) for index in range(total)]


def slot_time(windows: list[dict], weekday: int, index: int, total: int) -> time | None:
    for window in windows:
        if weekday in window.get("days") or []:
            start, end = _minutes(window["start"]), _minutes(window["end"])
            minute = start + (end - start) * (index + 1) // (total + 1)
            minute = (minute // 15) * 15
            return time(hour=minute // 60, minute=minute % 60)
    return None


def _format_sequence(formats: dict[str, int]) -> list[str]:
    remaining = dict(formats)
    sequence: list[str] = []
    while any(count > 0 for count in remaining.values()):
        for name in sorted(remaining, key=lambda key: (-remaining[key], key)):
            if remaining[name] > 0:
                sequence.append(name)
                remaining[name] -= 1
    return sequence


def pillar_performance(db: Session, tenant_id: UUID, platform: str, metric: str) -> dict[str, dict]:
    """Latest lifetime value per measured post, grouped by pillar. Unmeasured posts are not zero."""
    provider_metric = PLATFORM_METRIC.get(metric, {}).get(platform)
    if not provider_metric:
        return {}
    since = now() - timedelta(days=90)
    rows = db.execute(
        select(GrowthMedia.pillar_key, GrowthMetricObservation.value)
        .join(GrowthMetricObservation, GrowthMetricObservation.media_id == GrowthMedia.id)
        .join(GrowthAccount, GrowthAccount.id == GrowthMedia.account_id)
        .where(
            GrowthMedia.tenant_id == tenant_id,
            GrowthMedia.deleted_at.is_(None),
            GrowthMedia.pillar_key != "",
            GrowthMedia.posted_at >= since,
            GrowthAccount.platform == platform,
            GrowthMetricObservation.metric == provider_metric,
            GrowthMetricObservation.period == "lifetime",
            GrowthMetricObservation.status.in_(["recorded", "zero"]),
            GrowthMetricObservation.provenance == "live",
        )
    ).all()
    grouped: dict[str, list[int]] = {}
    for pillar, value in rows:
        if value is not None:
            grouped.setdefault(pillar, []).append(int(value))
    return {pillar: {"mean": round(sum(values) / len(values), 2), "sample": len(values), "metric": provider_metric} for pillar, values in grouped.items()}


def _weights(pillars: list[dict], performance: dict[str, dict]) -> tuple[dict[str, float], str]:
    keys = [pillar["key"] for pillar in pillars]
    if len(keys) < 2 or any(performance.get(key, {}).get("sample", 0) < PERFORMANCE_MINIMUM for key in keys):
        return {key: 1.0 for key in keys}, "insufficient_evidence"
    overall = sum(performance[key]["mean"] for key in keys) / len(keys)
    if overall <= 0:
        return {key: 1.0 for key in keys}, "insufficient_evidence"
    return {key: min(2.0, max(0.5, performance[key]["mean"] / overall)) for key in keys}, "weighted"


def plan_rolling_calendar(db: Session, *, tenant_id: UUID, actor_id: UUID | None, today: date | None = None) -> dict:
    strategy = active_strategy(db, tenant_id)
    if strategy is None:
        return {"status": "blocked", "detail": "Approve a strategy first. No calendar was invented.", "created": 0}
    if strategy.status == "paused":
        return {"status": "blocked", "detail": "The strategy is paused. Planning waits.", "created": 0}
    facts = {str(fact.id): fact for fact in approved_facts(db, tenant_id)}
    pillars = [pillar for pillar in loads(strategy.pillars_json, []) if any(item in facts for item in pillar.get("fact_ids") or [])]
    if not pillars:
        return {"status": "blocked", "detail": "No pillar still has an approved fact. Review the brand facts.", "created": 0}
    cadence = loads(strategy.cadence_json, {})
    moment = now()
    horizon = max(7, min(30, strategy.horizon_days))
    counts = {"created": 0, "replanned": 0, "withdrawn": 0, "kept": 0, "accounts": 0}
    skipped: list[str] = []
    history_since = moment - timedelta(days=60)
    recent_captions = [
        (str(row.id), "media", row.caption)
        for row in db.scalars(select(GrowthMedia).where(GrowthMedia.tenant_id == tenant_id, GrowthMedia.deleted_at.is_(None), GrowthMedia.posted_at >= history_since)).all()
        if row.caption.strip()
    ] + [
        (str(row.id), "creative", row.caption)
        for row in db.scalars(select(GrowthCreative).where(GrowthCreative.tenant_id == tenant_id, GrowthCreative.deleted_at.is_(None), GrowthCreative.status.in_(["approved", "needs_review"]), GrowthCreative.created_at >= history_since)).all()
        if row.caption.strip()
    ]
    events = db.scalars(select(GrowthBusinessEvent).where(GrowthBusinessEvent.tenant_id == tenant_id, GrowthBusinessEvent.deleted_at.is_(None), GrowthBusinessEvent.status == "active")).all()
    for raw_id, plan in cadence.items():
        account = db.get(GrowthAccount, UUID(raw_id))
        if account is None or account.tenant_id != tenant_id or account.deleted_at is not None:
            continue
        if account.status in {"disconnected", "revoked"}:
            skipped.append(f"{account.name or account.external_id}: disconnected")
            continue
        try:
            zone = ZoneInfo(account.timezone or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo("UTC")
        windows = loads(account.posting_windows, [])
        template = week_template(windows, int(plan.get("posts_per_week") or 0), account.daily_cap)
        if not template:
            skipped.append(f"{account.name or account.external_id}: no posting window")
            continue
        counts["accounts"] += 1
        formats = [name for name in _format_sequence(plan.get("formats") or {}) if name in PLATFORM_FORMATS[account.platform]] or ["image"]
        performance = pillar_performance(db, tenant_id, account.platform, strategy.optimization_metric)
        weights, verdict = _weights(pillars, performance)
        start_local = (today or moment.astimezone(zone).date())
        existing = {
            row.slot_key: row
            for row in db.scalars(
                select(GrowthCalendarItem).where(
                    GrowthCalendarItem.tenant_id == tenant_id,
                    GrowthCalendarItem.account_id == account.id,
                    GrowthCalendarItem.deleted_at.is_(None),
                    GrowthCalendarItem.planned_for >= moment - timedelta(days=30),
                )
            ).all()
        }
        usage = {pillar["key"]: 0 for pillar in pillars}
        fact_last: dict[str, datetime] = {}
        previous_pillar = ""
        for row in sorted(existing.values(), key=lambda item: aware(item.planned_for) or moment):
            if row.pillar_key in usage and row.status != "skipped":
                usage[row.pillar_key] += 1
                previous_pillar = row.pillar_key
            for fact in loads(row.brief_json, {}).get("facts") or []:
                fact_last[str(fact.get("id"))] = aware(row.planned_for) or moment
        position = 0
        for offset in range(horizon):
            local_day = start_local + timedelta(days=offset)
            day_slots = [entry for entry in template if entry[0] == local_day.weekday()]
            for weekday, index, total in day_slots:
                clock = slot_time(windows, weekday, index, total)
                if clock is None:
                    continue
                planned_local = datetime.combine(local_day, clock, tzinfo=zone)
                planned_utc = planned_local.astimezone(UTC)
                slot_key = f"{local_day.isoformat()}#{index}"
                position += 1
                current = existing.get(slot_key)
                if current is not None and (current.strategy_id == strategy.id or current.status not in OPEN_STATUSES or current.publication_id is not None):
                    counts["kept"] += 1
                    continue
                if planned_utc < moment + timedelta(minutes=LEAD_MINUTES):
                    continue
                chosen = _choose_pillar(pillars, usage, weights, previous_pillar)
                usage[chosen["key"]] += 1
                previous_pillar = chosen["key"]
                event = next((item for item in events if item.starts_on <= local_day.isoformat() <= item.ends_on), None)
                fact_pool = [item for item in (loads(event.fact_ids, []) if event is not None else []) if item in facts] or [item for item in chosen["fact_ids"] if item in facts]
                selected, repetition, prior = _choose_fact(fact_pool, facts, fact_last, recent_captions)
                fact_last[str(selected.id)] = planned_utc
                fmt = formats[(position - 1) % len(formats)]
                brief = {
                    "pillar": {"key": chosen["key"], "name": chosen["name"]},
                    "facts": [_fact_brief(selected)] + [_fact_brief(facts[item]) for item in fact_pool if item != str(selected.id)][:2],
                    "format": fmt,
                    "audience": (loads(strategy.audiences_json, []) or [""])[0],
                    "objective": strategy.objective,
                    "call_to_action": strategy.call_to_action,
                    "destination": {"kind": strategy.destination_kind, "form_key_id": str(strategy.destination_form_key_id or ""), "url": strategy.destination_url},
                    "repetition": repetition,
                    "prior_content": prior,
                    "performance": {
                        "metric": strategy.optimization_metric,
                        "provider_metric": PLATFORM_METRIC.get(strategy.optimization_metric, {}).get(account.platform, ""),
                        "pillar": performance.get(chosen["key"]),
                        "verdict": verdict,
                        "rule": f"Pillar weights change only when every pillar has at least {PERFORMANCE_MINIMUM} measured live posts in 90 days.",
                    },
                    "event": {"id": str(event.id), "title": event.title, "kind": event.kind, "starts_on": event.starts_on, "ends_on": event.ends_on} if event is not None else None,
                    "strategy_version": strategy.version,
                    "rationale": _rationale(chosen, selected, verdict, repetition, event),
                }
                if current is not None:
                    item = current
                    counts["replanned"] += 1
                    if item.status != "planned" or item.creative_id is not None:
                        _withdraw(db, tenant_id=tenant_id, actor_id=actor_id, item=item, strategy=strategy)
                        counts["withdrawn"] += 1
                else:
                    item = GrowthCalendarItem(tenant_id=tenant_id, created_by=actor_id, account_id=account.id, slot_key=slot_key)
                    db.add(item)
                    counts["created"] += 1
                item.strategy_id = strategy.id
                item.planned_for = planned_utc
                item.local_date = local_day.isoformat()
                item.pillar_key = chosen["key"]
                item.format = fmt
                item.audience = brief["audience"]
                item.objective = strategy.objective
                item.call_to_action = strategy.call_to_action
                item.event_id = event.id if event is not None else None
                item.brief_json = dumps(brief)
                item.status = "planned"
                item.blocker = ""
                existing[slot_key] = item
        db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="growth.calendar_plan",
        entity_type="growth_strategy",
        entity_id=str(strategy.id),
        after={**counts, "skipped": skipped[:10], "horizon_days": horizon},
        actor_type="human" if actor_id else "ai",
    )
    detail = f"{counts['created']} new slot(s), {counts['replanned']} re-planned, {counts['kept']} kept. Nothing was published."
    if counts["withdrawn"]:
        detail += f" {counts['withdrawn']} slot(s) from a replaced strategy version had unpublished creative and publish requests withdrawn."
    if skipped:
        detail += " Skipped: " + "; ".join(skipped[:3]) + "."
    return {"status": "planned", "detail": detail, **counts, "skipped": skipped}


def _choose_pillar(pillars: list[dict], usage: dict[str, int], weights: dict[str, float], previous: str) -> dict:
    candidates = [pillar for pillar in pillars if pillar["key"] != previous] or pillars
    return min(candidates, key=lambda pillar: (usage[pillar["key"]] / weights.get(pillar["key"], 1.0), pillar["key"]))


def _choose_fact(pool: list[str], facts: dict[str, BrandFact], last_used: dict[str, datetime], captions: list[tuple[str, str, str]]) -> tuple[BrandFact, dict, list[dict]]:
    ordered = sorted(pool, key=lambda item: (last_used.get(item, datetime.min.replace(tzinfo=UTC)), item))
    best: tuple[BrandFact, float, list[dict]] | None = None
    for item in ordered:
        fact = facts[item]
        scored = sorted(((similarity(fact.statement, text), ref, kind) for ref, kind, text in captions), reverse=True)[:3]
        top = scored[0][0] if scored else 0.0
        prior = [{"id": ref, "kind": kind, "similarity": score} for score, ref, kind in scored if score > 0]
        if top < SIMILARITY_THRESHOLD:
            return fact, {"max_similarity": top, "threshold": SIMILARITY_THRESHOLD, "passed": True}, prior
        if best is None or top < best[1]:
            best = (fact, top, prior)
    fact, top, prior = best if best is not None else (facts[ordered[0]], 0.0, [])
    return fact, {
        "max_similarity": top,
        "threshold": SIMILARITY_THRESHOLD,
        "passed": False,
        "note": "Every approved fact in this pillar was used in a recent post. The creative goes to review for a different angle.",
    }, prior


def _fact_brief(fact: BrandFact) -> dict:
    return {"id": str(fact.id), "category": fact.category, "statement": fact.statement, "source_url": fact.source_url}


def _rationale(pillar: dict, fact: BrandFact, verdict: str, repetition: dict, event: GrowthBusinessEvent | None) -> str:
    parts = [f"Pillar {pillar['name']} had the fewest planned posts for this account."]
    if verdict == "weighted":
        parts.append("Pillar weights use measured live performance.")
    else:
        parts.append("Performance evidence was insufficient, so pillars rotate evenly.")
    parts.append(f"Fact chosen: the least recently used approved {fact.category}.")
    if not repetition.get("passed"):
        parts.append("Repetition risk is flagged for review.")
    if event is not None:
        parts.append(f"Business event in range: {event.title}.")
    return " ".join(parts)


def _withdraw(db: Session, *, tenant_id: UUID, actor_id: UUID | None, item: GrowthCalendarItem, strategy: GrowthStrategy) -> None:
    """The slot never reached Meta. Nothing approved under the replaced version may post from it."""
    creative = db.get(GrowthCreative, item.creative_id) if item.creative_id else None
    before = {"status": item.status, "strategy_id": str(item.strategy_id or ""), "creative_id": str(item.creative_id or ""), "creative_status": creative.status if creative is not None else ""}
    if creative is not None and creative.tenant_id == tenant_id and creative.status in {"draft", "needs_review", "approved"}:
        creative.status = "superseded"
    reason = f"Strategy version {strategy.version} replaced the version this slot was planned under."
    withdraw_publish_requests(db, tenant_id=tenant_id, actor_id=actor_id, item_id=item.id, reason=reason)
    item.creative_id = None
    item.tracking_link_id = None
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="growth.item_superseded",
        entity_type="growth_calendar_item",
        entity_id=str(item.id),
        before=before,
        after={"status": "planned", "strategy_id": str(strategy.id), "reason": reason},
        actor_type="human" if actor_id else "ai",
    )


def item_out(row: GrowthCalendarItem, account: GrowthAccount | None, creative: GrowthCreative | None, publication: GrowthPublication | None) -> dict:
    return {
        "id": str(row.id),
        "account_id": str(row.account_id),
        "account_name": (account.name or account.username or account.external_id) if account is not None else "",
        "platform": account.platform if account is not None else "",
        "account_provenance": account.provenance if account is not None else "",
        "planned_for": iso(row.planned_for),
        "local_date": row.local_date,
        "pillar_key": row.pillar_key,
        "format": row.format,
        "status": row.status,
        "blocker": row.blocker,
        "brief": loads(row.brief_json, {}),
        "creative": {"id": str(creative.id), "status": creative.status, "version": creative.version, "quality_state": creative.quality_state} if creative is not None else None,
        "publication": {
            "id": str(publication.id),
            "status": publication.status,
            "external_id": publication.external_id,
            "permalink": publication.permalink,
            "provenance": publication.provenance,
            "last_error": publication.last_error,
        }
        if publication is not None
        else None,
    }


def calendar_view(db: Session, tenant_id: UUID, *, start: datetime, end: datetime, account_id: UUID | None = None) -> dict:
    stmt = select(GrowthCalendarItem).where(
        GrowthCalendarItem.tenant_id == tenant_id,
        GrowthCalendarItem.deleted_at.is_(None),
        GrowthCalendarItem.planned_for >= start,
        GrowthCalendarItem.planned_for < end,
    )
    if account_id is not None:
        stmt = stmt.where(GrowthCalendarItem.account_id == account_id)
    rows = db.scalars(stmt.order_by(GrowthCalendarItem.planned_for.asc())).all()
    accounts = {row.id: row for row in db.scalars(select(GrowthAccount).where(GrowthAccount.tenant_id == tenant_id)).all()}
    creative_ids = [row.creative_id for row in rows if row.creative_id]
    publication_ids = [row.publication_id for row in rows if row.publication_id]
    creatives = {row.id: row for row in db.scalars(select(GrowthCreative).where(GrowthCreative.tenant_id == tenant_id, GrowthCreative.id.in_(creative_ids))).all()} if creative_ids else {}
    publications = {row.id: row for row in db.scalars(select(GrowthPublication).where(GrowthPublication.tenant_id == tenant_id, GrowthPublication.id.in_(publication_ids))).all()} if publication_ids else {}
    items = [item_out(row, accounts.get(row.account_id), creatives.get(row.creative_id), publications.get(row.publication_id)) for row in rows]
    by_status: dict[str, int] = {}
    for item in items:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    return {"start": iso(start), "end": iso(end), "items": items, "by_status": by_status}


def owned_item(db: Session, tenant_id: UUID, item_id: UUID) -> GrowthCalendarItem:
    row = db.scalar(select(GrowthCalendarItem).where(GrowthCalendarItem.tenant_id == tenant_id, GrowthCalendarItem.id == item_id, GrowthCalendarItem.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    return row


def skip_item(db: Session, *, tenant_id: UUID, actor_id: UUID, item_id: UUID, reason: str) -> GrowthCalendarItem:
    row = owned_item(db, tenant_id, item_id)
    if row.status in {"published", "publishing"}:
        raise HTTPException(status_code=409, detail="A published or publishing item cannot be skipped.")
    before = row.status
    row.status = "skipped"
    row.blocker = reason.strip()[:500] or "Skipped by an operator."
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.item_skip", entity_type="growth_calendar_item", entity_id=str(row.id), before={"status": before}, after={"status": "skipped", "reason": row.blocker})
    return row


def strategy_for(db: Session, item: GrowthCalendarItem) -> GrowthStrategy | None:
    row = db.get(GrowthStrategy, item.strategy_id)
    return row if row is not None and row.tenant_id == item.tenant_id else None
