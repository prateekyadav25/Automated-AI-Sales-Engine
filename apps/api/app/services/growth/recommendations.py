"""Reviewable recommendations from measured live performance.

Each one states what was observed, the sample, the limitation, and the
proposed change. Below the minimum sample the verdict is insufficient
evidence. Nothing here changes the strategy, the copy, the cadence, or spend.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.growth import GrowthAccount, GrowthMedia, GrowthMetricObservation, GrowthRecommendation
from app.services.audit import write_audit
from app.services.growth.common import aware, dumps, iso, loads, now
from app.services.growth.planner import PLATFORM_METRIC
from app.services.growth.strategy import active_strategy

MIN_SAMPLE = 5


def _measured(db: Session, tenant_id: UUID, platform: str, metric: str) -> list[tuple[GrowthMedia, int, GrowthAccount]]:
    rows = db.execute(
        select(GrowthMedia, GrowthMetricObservation.value, GrowthAccount)
        .join(GrowthMetricObservation, GrowthMetricObservation.media_id == GrowthMedia.id)
        .join(GrowthAccount, GrowthAccount.id == GrowthMedia.account_id)
        .where(
            GrowthMedia.tenant_id == tenant_id,
            GrowthMedia.deleted_at.is_(None),
            GrowthMedia.posted_at >= now() - timedelta(days=90),
            GrowthAccount.platform == platform,
            GrowthMetricObservation.metric == metric,
            GrowthMetricObservation.period == "lifetime",
            GrowthMetricObservation.status.in_(["recorded", "zero"]),
            GrowthMetricObservation.provenance == "live",
        )
    ).all()
    return [(media, int(value), account) for media, value, account in rows if value is not None]


def _bucket_hour(media: GrowthMedia, account: GrowthAccount) -> str:
    try:
        zone = ZoneInfo(account.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    posted = aware(media.posted_at)
    hour = posted.astimezone(zone).hour if posted is not None else -1
    return "morning (05-12)" if 5 <= hour < 12 else "afternoon (12-17)" if 12 <= hour < 17 else "evening (17-23)" if 17 <= hour < 23 else "night"


def _compare(kind: str, platform: str, metric: str, groups: dict[str, list[int]]) -> dict:
    sizes = {key: len(values) for key, values in groups.items()}
    sample = sum(sizes.values())
    eligible = {key: values for key, values in groups.items() if len(values) >= MIN_SAMPLE}
    if len(eligible) < 2:
        return {
            "kind": kind,
            "observation": f"{sample} measured live {platform} post(s) across {len(groups)} {kind} group(s).",
            "evidence": {"platform": platform, "metric": metric, "group_sizes": sizes},
            "sample_size": sample,
            "limitation": f"A comparison needs at least two {kind} groups with {MIN_SAMPLE} measured live posts each. Missing readings are not zero.",
            "proposed_change": "Keep the current strategy. Collect more measured posts.",
            "verdict": "insufficient_evidence",
        }
    means = {key: round(sum(values) / len(values), 1) for key, values in eligible.items()}
    best = max(means, key=means.get)
    worst = min(means, key=means.get)
    return {
        "kind": kind,
        "observation": f"On {platform}, {best} averaged {means[best]} {metric} per post and {worst} averaged {means[worst]}.",
        "evidence": {"platform": platform, "metric": metric, "means": means, "group_sizes": sizes},
        "sample_size": sample,
        "limitation": "This is an observed association over 90 days, not a controlled test. Audience, topic, and timing also differ between posts.",
        "proposed_change": f"Consider giving {best} more weight in the next strategy version. A person decides; nothing was changed.",
        "verdict": "proposal_only",
    }


def generate(db: Session, *, tenant_id: UUID, actor_id: UUID | None) -> list[dict]:
    strategy = active_strategy(db, tenant_id)
    objective = strategy.optimization_metric if strategy is not None else "reach"
    platforms = sorted({row.platform for row in db.scalars(select(GrowthAccount).where(GrowthAccount.tenant_id == tenant_id, GrowthAccount.deleted_at.is_(None))).all()})
    produced: list[dict] = []
    for platform in platforms:
        metric = PLATFORM_METRIC.get(objective, PLATFORM_METRIC["reach"]).get(platform) or PLATFORM_METRIC["reach"][platform]
        measured = _measured(db, tenant_id, platform, metric)
        by_format: dict[str, list[int]] = {}
        by_pillar: dict[str, list[int]] = {}
        by_time: dict[str, list[int]] = {}
        for media, value, account in measured:
            by_format.setdefault(media.format or "unknown", []).append(value)
            if media.pillar_key:
                by_pillar.setdefault(media.pillar_key, []).append(value)
            by_time.setdefault(_bucket_hour(media, account), []).append(value)
        produced += [_compare("format", platform, metric, by_format), _compare("pillar", platform, metric, by_pillar), _compare("timing", platform, metric, by_time)]
    for account in db.scalars(select(GrowthAccount).where(GrowthAccount.tenant_id == tenant_id, GrowthAccount.deleted_at.is_(None), GrowthAccount.status.in_(["needs_reconnect", "expired", "missing_permissions"]))).all():
        produced.append(
            {
                "kind": "account",
                "observation": f"{account.platform.title()} {account.name or account.external_id} is {account.status}: {account.last_error or 'no detail'}",
                "evidence": {"account_id": str(account.id), "status": account.status},
                "sample_size": 0,
                "limitation": "Publishing and insights for this account wait until it is reconnected.",
                "proposed_change": "Reconnect the account with the missing permissions.",
                "verdict": "action_required",
            }
        )
    for row in db.scalars(select(GrowthRecommendation).where(GrowthRecommendation.tenant_id == tenant_id, GrowthRecommendation.status == "open", GrowthRecommendation.deleted_at.is_(None))).all():
        row.status = "superseded"
    for item in produced:
        db.add(
            GrowthRecommendation(
                tenant_id=tenant_id,
                created_by=actor_id,
                kind=item["kind"],
                observation=item["observation"],
                evidence_json=dumps(item["evidence"]),
                sample_size=item["sample_size"],
                limitation=item["limitation"],
                proposed_change=item["proposed_change"],
                verdict=item["verdict"],
            )
        )
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.recommendations", entity_type="growth_recommendation", entity_id="", after={"count": len(produced)}, actor_type="human" if actor_id else "ai")
    return open_recommendations(db, tenant_id)


def open_recommendations(db: Session, tenant_id: UUID) -> list[dict]:
    rows = db.scalars(
        select(GrowthRecommendation)
        .where(GrowthRecommendation.tenant_id == tenant_id, GrowthRecommendation.status == "open", GrowthRecommendation.deleted_at.is_(None))
        .order_by(GrowthRecommendation.created_at.desc())
    ).all()
    return [
        {
            "id": str(row.id),
            "kind": row.kind,
            "observation": row.observation,
            "evidence": loads(row.evidence_json, {}),
            "sample_size": row.sample_size,
            "limitation": row.limitation,
            "proposed_change": row.proposed_change,
            "verdict": row.verdict,
            "created_at": iso(row.created_at),
        }
        for row in rows
    ]


def decide(db: Session, *, tenant_id: UUID, actor_id: UUID, recommendation_id: UUID, decision: str) -> dict:
    row = db.scalar(select(GrowthRecommendation).where(GrowthRecommendation.tenant_id == tenant_id, GrowthRecommendation.id == recommendation_id, GrowthRecommendation.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if decision not in {"accepted", "dismissed"}:
        raise HTTPException(status_code=422, detail="Decision must be accepted or dismissed.")
    row.status = decision
    row.decided_by = actor_id
    row.decided_at = now()
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.recommendation_decide", entity_type="growth_recommendation", entity_id=str(row.id), after={"status": decision, "note": "Accepting records the decision. Edit the strategy to apply it."})
    return {"id": str(row.id), "status": row.status, "detail": "Recorded. The strategy is unchanged until someone edits and approves a new version."}
