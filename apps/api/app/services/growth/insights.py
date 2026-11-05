"""Organic performance read-back from Meta insights, and period reporting.

Each reading keeps its metric, period, end time, retrieval time, API version,
endpoint, and provenance. Meta returns an empty set when data is unavailable;
that stays unavailable, not zero. A returned zero stays zero. A later reading
of the same period replaces the earlier one and is never added to it. Meta can
delay insights by up to 48 hours. Fixture readings never enter live totals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.growth import GrowthAccount, GrowthMedia, GrowthMetricObservation
from app.providers.meta_growth import (
    FACEBOOK_PAGE_METRICS,
    FACEBOOK_POST_METRICS,
    FACEBOOK_VIDEO_METRICS,
    INSTAGRAM_ACCOUNT_METRICS,
    INSTAGRAM_FOLLOWER_METRIC,
    INSTAGRAM_MEDIA_METRICS,
    GraphResult,
    MetaGrowthClient,
)
from app.services.audit import write_audit
from app.services.growth.accounts import live_client, live_read_block, mark_auth_failure, owned_account, token_problem
from app.services.growth.common import aware, iso, now

GOOD = ("recorded", "zero")
ADDITIVE = {
    "views", "total_interactions", "profile_links_taps", "likes", "comments", "saved", "shares", "follows",
    "profile_visits", "page_media_view", "page_post_engagements", "page_daily_follows_unique", "page_views_total",
    "page_total_actions", "post_media_view", "post_clicks", "post_video_views",
}
UNIQUE = {"reach", "accounts_engaged", "page_total_media_view_unique", "post_total_media_view_unique"}
LATEST = {INSTAGRAM_FOLLOWER_METRIC, "ig_reels_avg_watch_time"}
DELAY_NOTE = "Meta can delay insights by up to 48 hours. Recent days may be incomplete."


def _number(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value >= 0:
        return int(round(value))
    return None


def parse_insights(payload: dict) -> dict[str, list[tuple[str, int | None, str]]]:
    """Map metric name to (end_time, value, note). An absent metric is absent, not zero."""
    found: dict[str, list[tuple[str, int | None, str]]] = {}
    for entry in payload.get("data") or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name = str(entry["name"])
        rows: list[tuple[str, int | None, str]] = []
        total = entry.get("total_value")
        if isinstance(total, dict) and "value" in total:
            rows.append(("", _number(total.get("value")), "" if _number(total.get("value")) is not None else "Meta returned a non-numeric total."))
        for point in entry.get("values") or []:
            if not isinstance(point, dict):
                continue
            raw = point.get("value")
            note = "Meta returned a breakdown, which is not stored as one number." if isinstance(raw, dict) else ""
            rows.append((str(point.get("end_time") or ""), _number(raw), note))
        found[name] = rows
    return found


def _period_key(end_time: str) -> tuple[str, datetime | None]:
    if not end_time:
        return "lifetime", None
    try:
        moment = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return end_time[:40], None
    return moment.astimezone(UTC).date().isoformat(), moment


def _store(db: Session, *, account: GrowthAccount, media: GrowthMedia | None, scope: str, external_id: str, metric: str, period: str, period_key: str, period_end: datetime | None, value: int | None, status: str, error: str, endpoint: str, api_version: str, provenance: str, actor_id: UUID | None) -> GrowthMetricObservation:
    row = db.scalar(
        select(GrowthMetricObservation).where(
            GrowthMetricObservation.tenant_id == account.tenant_id,
            GrowthMetricObservation.scope == scope,
            GrowthMetricObservation.external_id == external_id,
            GrowthMetricObservation.metric == metric,
            GrowthMetricObservation.period == period,
            GrowthMetricObservation.period_key == period_key,
        )
    )
    moment = now()
    if row is not None and row.status in GOOD and status not in GOOD:
        row.error = error[:1000]
        row.retrieved_at = moment
        return row
    if row is None:
        row = GrowthMetricObservation(
            tenant_id=account.tenant_id,
            created_by=actor_id,
            account_id=account.id,
            media_id=media.id if media is not None else None,
            scope=scope,
            external_id=external_id,
            metric=metric,
            period=period,
            period_key=period_key,
            retrieved_at=moment,
            status=status,
        )
        db.add(row)
    row.period_end = period_end
    row.value = value
    row.status = status
    row.retrieved_at = moment
    row.api_version = api_version
    row.endpoint = endpoint[:200]
    row.provenance = provenance
    row.error = error[:1000]
    return row


def _read_metrics(fetch, metrics: tuple[str, ...]) -> tuple[dict[str, list[tuple[str, int | None, str]]], dict[str, str], GraphResult | None, int]:
    """Read a metric list. If Meta rejects the list, read each metric alone so one deprecated metric does not hide the rest.

    Returns the parsed values, the rejected metrics, a blocking failure, and the number of HTTP calls made.
    """
    result = fetch(metrics)
    if result.ok:
        return parse_insights(result.data), {}, None, 1
    if result.failure_class in {"AUTH", "RATE_LIMIT", "PUBLISH_LIMIT", "NETWORK", "TRANSIENT", "PERMISSION"}:
        return {}, {}, result, 1
    parsed: dict[str, list[tuple[str, int | None, str]]] = {}
    rejected: dict[str, str] = {}
    calls = 1
    for metric in metrics:
        single = fetch((metric,))
        calls += 1
        if single.ok:
            parsed.update(parse_insights(single.data))
        elif single.failure_class == "INVALID":
            rejected[metric] = single.error_message
        else:
            return parsed, rejected, single, calls
    return parsed, rejected, None, calls


def _open(db: Session, tenant_id: UUID, account: GrowthAccount, client: MetaGrowthClient | None) -> tuple[MetaGrowthClient | None, bool, str]:
    if client is not None:
        return client, False, ""
    if account.provenance == "fixture":
        return None, False, "Fixture accounts are not read from Meta."
    blocked = live_read_block(db, tenant_id)
    if blocked:
        return None, False, blocked
    problem = token_problem(account)
    if problem:
        return None, False, problem
    graph = live_client(db, account)
    return (graph, True, "") if graph is not None else (None, False, "No stored token. Reconnect the account.")


def collect_account_insights(db: Session, *, tenant_id: UUID, actor_id: UUID | None, account_id: UUID, client: MetaGrowthClient | None = None, provenance: str = "live", days: int = 7) -> dict:
    account = owned_account(db, tenant_id, account_id)
    graph, owned, blocked = _open(db, tenant_id, account, client)
    if graph is None:
        return {"status": "blocked", "stored": 0, "http_calls": 0, "detail": blocked}
    stored = calls = 0
    try:
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        if account.platform == "facebook":
            since = int((today - timedelta(days=days)).timestamp())
            until = int(today.timestamp())

            def fetch(metrics):
                return graph.fb_page_insights(account.external_id, metrics, period="day", since=since, until=until)

            parsed, rejected, failure, made = _read_metrics(fetch, FACEBOOK_PAGE_METRICS)
            calls += made
            stored += _store_series(db, account, parsed, rejected, failure, FACEBOOK_PAGE_METRICS, f"{account.external_id}/insights", graph.version, provenance, actor_id, default_end=today)
        else:
            for offset in range(days, 0, -1):
                start = today - timedelta(days=offset)
                end = start + timedelta(days=1)

                def fetch(metrics, start=start, end=end):
                    return graph.ig_account_insights(account.external_id, metrics, period="day", since=int(start.timestamp()), until=int(end.timestamp()), total_value=True)

                parsed, rejected, failure, made = _read_metrics(fetch, INSTAGRAM_ACCOUNT_METRICS)
                calls += made
                stamped = {name: [(end.strftime("%Y-%m-%dT%H:%M:%S+0000"), value, note) for _end, value, note in rows] for name, rows in parsed.items()}
                stored += _store_series(db, account, stamped, rejected, failure, INSTAGRAM_ACCOUNT_METRICS, f"{account.external_id}/insights", graph.version, provenance, actor_id, default_end=end)
                if failure is not None and failure.failure_class in {"AUTH", "RATE_LIMIT"}:
                    break
            calls += 1
            since = int((today - timedelta(days=min(days, 30))).timestamp())
            follower = graph.ig_account_insights(account.external_id, (INSTAGRAM_FOLLOWER_METRIC,), period="day", since=since, until=int(today.timestamp()), total_value=False)
            if follower.ok:
                stored += _store_series(db, account, parse_insights(follower.data), {}, None, (INSTAGRAM_FOLLOWER_METRIC,), f"{account.external_id}/insights", graph.version, provenance, actor_id)
            elif follower.failure_class == "INVALID":
                stored += _store_series(db, account, {}, {INSTAGRAM_FOLLOWER_METRIC: follower.error_message}, None, (INSTAGRAM_FOLLOWER_METRIC,), f"{account.external_id}/insights", graph.version, provenance, actor_id, default_end=today)
        db.flush()
        write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.insights_account", entity_type="growth_account", entity_id=str(account.id), after={"stored": stored, "http_calls": calls, "provenance": provenance}, actor_type="human" if actor_id else "ai")
        return {"status": "recorded", "stored": stored, "http_calls": calls, "detail": DELAY_NOTE}
    finally:
        if owned:
            graph.close()


def _store_series(db, account, parsed, rejected, failure, metrics, endpoint, api_version, provenance, actor_id, *, default_end: datetime | None = None) -> int:
    stored = 0
    if failure is not None:
        if failure.failure_class == "AUTH":
            mark_auth_failure(account, failure.error_message)
        for metric in metrics:
            key = default_end.astimezone(UTC).date().isoformat() if default_end is not None else "latest"
            _store(db, account=account, media=None, scope="account", external_id=account.external_id, metric=metric, period="day", period_key=key, period_end=default_end, value=None, status="failed", error=failure.error_message, endpoint=endpoint, api_version=api_version, provenance=provenance, actor_id=actor_id)
            stored += 1
        return stored
    for metric in metrics:
        if metric in rejected:
            key = default_end.astimezone(UTC).date().isoformat() if default_end is not None else "latest"
            _store(db, account=account, media=None, scope="account", external_id=account.external_id, metric=metric, period="day", period_key=key, period_end=default_end, value=None, status="unsupported", error=rejected[metric], endpoint=endpoint, api_version=api_version, provenance=provenance, actor_id=actor_id)
            stored += 1
            continue
        rows = parsed.get(metric)
        if not rows:
            if default_end is not None:
                _store(db, account=account, media=None, scope="account", external_id=account.external_id, metric=metric, period="day", period_key=default_end.astimezone(UTC).date().isoformat(), period_end=default_end, value=None, status="unavailable", error="Meta returned no value for this metric and period.", endpoint=endpoint, api_version=api_version, provenance=provenance, actor_id=actor_id)
                stored += 1
            continue
        for end_time, value, note in rows:
            key, period_end = _period_key(end_time)
            if period_end is None and default_end is not None:
                key, period_end = default_end.astimezone(UTC).date().isoformat(), default_end
            status = "unavailable" if value is None else ("zero" if value == 0 else "recorded")
            _store(db, account=account, media=None, scope="account", external_id=account.external_id, metric=metric, period="day", period_key=key, period_end=period_end, value=value, status=status, error=note, endpoint=endpoint, api_version=api_version, provenance=provenance, actor_id=actor_id)
            stored += 1
    return stored


def collect_media_insights(db: Session, *, tenant_id: UUID, actor_id: UUID | None, account_id: UUID, client: MetaGrowthClient | None = None, provenance: str = "live", limit: int = 50) -> dict:
    account = owned_account(db, tenant_id, account_id)
    graph, owned, blocked = _open(db, tenant_id, account, client)
    if graph is None:
        return {"status": "blocked", "stored": 0, "http_calls": 0, "detail": blocked}
    stored = calls = 0
    try:
        since = now() - timedelta(days=90)
        media_rows = db.scalars(
            select(GrowthMedia)
            .where(GrowthMedia.tenant_id == tenant_id, GrowthMedia.account_id == account.id, GrowthMedia.deleted_at.is_(None))
            .order_by(GrowthMedia.posted_at.desc())
            .limit(limit)
        ).all()
        for media in media_rows:
            if aware(media.posted_at) is not None and aware(media.posted_at) < since and media.origin != "engine":
                continue
            if account.platform == "instagram":
                metrics = INSTAGRAM_MEDIA_METRICS["REELS" if media.media_product_type == "REELS" else "FEED"]

                def fetch(names, media=media):
                    return graph.ig_media_insights(media.external_id, names)
            else:
                metrics = FACEBOOK_POST_METRICS + (FACEBOOK_VIDEO_METRICS if media.format == "reel" else ())

                def fetch(names, media=media):
                    return graph.fb_post_insights(media.external_id, names)

            parsed, rejected, failure, made = _read_metrics(fetch, metrics)
            calls += made
            endpoint = f"{media.external_id}/insights"
            for metric in metrics:
                if failure is not None:
                    status, value, error = "failed", None, failure.error_message
                elif metric in rejected:
                    status, value, error = "unsupported", None, rejected[metric]
                else:
                    rows = parsed.get(metric) or []
                    value = rows[-1][1] if rows else None
                    error = (rows[-1][2] if rows else "") or ("" if rows else "Meta returned no value for this metric.")
                    status = "unavailable" if value is None else ("zero" if value == 0 else "recorded")
                _store(db, account=account, media=media, scope="media", external_id=media.external_id, metric=metric, period="lifetime", period_key="lifetime", period_end=None, value=value, status=status, error=error, endpoint=endpoint, api_version=graph.version, provenance=provenance, actor_id=actor_id)
                stored += 1
            if failure is not None and failure.failure_class == "AUTH":
                mark_auth_failure(account, failure.error_message)
                break
            if failure is not None and failure.failure_class == "RATE_LIMIT":
                break
        db.flush()
        write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.insights_media", entity_type="growth_account", entity_id=str(account.id), after={"stored": stored, "http_calls": calls, "provenance": provenance}, actor_type="human" if actor_id else "ai")
        return {"status": "recorded", "stored": stored, "http_calls": calls, "detail": DELAY_NOTE}
    finally:
        if owned:
            graph.close()


def _account_section(db: Session, account: GrowthAccount, start: datetime, end: datetime, provenance: str) -> dict:
    rows = db.scalars(
        select(GrowthMetricObservation).where(
            GrowthMetricObservation.tenant_id == account.tenant_id,
            GrowthMetricObservation.account_id == account.id,
            GrowthMetricObservation.scope == "account",
            GrowthMetricObservation.provenance == provenance,
            GrowthMetricObservation.period == "day",
            GrowthMetricObservation.period_end >= start,
            GrowthMetricObservation.period_end <= end,
            GrowthMetricObservation.deleted_at.is_(None),
        )
    ).all()
    range_days = max(1, round((end - start).total_seconds() / 86400))
    metrics: dict[str, dict] = {}
    for row in rows:
        entry = metrics.setdefault(row.metric, {"metric": row.metric, "values": [], "errors": [], "statuses": {}})
        entry["statuses"][row.status] = entry["statuses"].get(row.status, 0) + 1
        if row.status in GOOD and row.value is not None:
            entry["values"].append((row.period_key, row.value, row.retrieved_at))
        elif row.error:
            entry["errors"].append(row.error)
    out: list[dict] = []
    for name, entry in sorted(metrics.items()):
        values = sorted(entry["values"])
        days_with_value = len({key for key, _value, _at in values})
        if not values:
            out.append({"metric": name, "value": None, "aggregation": "unavailable", "coverage_days": 0, "range_days": range_days, "statuses": entry["statuses"], "error": (entry["errors"] or [""])[0]})
            continue
        if name in LATEST:
            value, aggregation = values[-1][1], "latest daily value"
        elif name in UNIQUE:
            value, aggregation = round(sum(item[1] for item in values) / len(values), 1), "average daily value (unique counts are not added across days)"
        else:
            value, aggregation = sum(item[1] for item in values), "sum of daily values"
        out.append(
            {
                "metric": name,
                "value": value,
                "aggregation": aggregation,
                "coverage_days": days_with_value,
                "range_days": range_days,
                "partial": days_with_value < range_days,
                "retrieved_at": iso(max(item[2] for item in values)),
                "statuses": entry["statuses"],
            }
        )
    return {"metrics": out}


def _media_section(db: Session, account: GrowthAccount, start: datetime, end: datetime, provenance: str) -> dict:
    media_rows = db.scalars(
        select(GrowthMedia).where(
            GrowthMedia.tenant_id == account.tenant_id,
            GrowthMedia.account_id == account.id,
            GrowthMedia.deleted_at.is_(None),
            GrowthMedia.posted_at >= start,
            GrowthMedia.posted_at < end,
        )
    ).all()
    posts: list[dict] = []
    totals: dict[str, dict] = {}
    for media in media_rows:
        readings = db.scalars(
            select(GrowthMetricObservation).where(
                GrowthMetricObservation.tenant_id == account.tenant_id,
                GrowthMetricObservation.scope == "media",
                GrowthMetricObservation.external_id == media.external_id,
                GrowthMetricObservation.provenance == provenance,
                GrowthMetricObservation.deleted_at.is_(None),
            )
        ).all()
        if provenance != media.provenance and not readings:
            continue
        values = {row.metric: (row.value if row.status in GOOD else None) for row in readings}
        statuses = {row.metric: row.status for row in readings}
        retrieved = max((row.retrieved_at for row in readings), default=None)
        posts.append(
            {
                "id": str(media.id),
                "external_id": media.external_id,
                "origin": media.origin,
                "format": media.format,
                "pillar_key": media.pillar_key,
                "posted_at": iso(media.posted_at),
                "permalink": media.permalink,
                "caption": media.caption[:180],
                "metrics": values,
                "statuses": statuses,
                "retrieved_at": iso(retrieved),
                "measured": bool(readings),
            }
        )
        for metric, value in values.items():
            bucket = totals.setdefault(metric, {"metric": metric, "sum": 0, "posts_with_value": 0, "posts_without_value": 0})
            if value is None:
                bucket["posts_without_value"] += 1
            else:
                bucket["posts_with_value"] += 1
                if metric in ADDITIVE:
                    bucket["sum"] += value
    for metric, bucket in totals.items():
        if metric not in ADDITIVE or bucket["posts_with_value"] == 0:
            bucket["sum"] = None
    return {
        "posts": sorted(posts, key=lambda item: item["posted_at"], reverse=True),
        "totals": sorted(totals.values(), key=lambda item: item["metric"]),
        "unmeasured_posts": sum(1 for post in posts if not post["measured"]),
    }


def performance_report(db: Session, tenant_id: UUID, *, start: datetime, end: datetime, account_id: UUID | None = None) -> dict:
    stmt = select(GrowthAccount).where(GrowthAccount.tenant_id == tenant_id, GrowthAccount.deleted_at.is_(None))
    if account_id is not None:
        stmt = stmt.where(GrowthAccount.id == account_id)
    accounts = db.scalars(stmt.order_by(GrowthAccount.platform.asc())).all()
    sections = []
    for account in accounts:
        provenance = "fixture" if account.provenance == "fixture" else "live"
        sections.append(
            {
                "account": {"id": str(account.id), "platform": account.platform, "name": account.name or account.username or account.external_id, "provenance": account.provenance, "status": account.status},
                "evidence": provenance,
                "account_metrics": _account_section(db, account, start, end, provenance),
                "media": _media_section(db, account, start, end, provenance),
            }
        )
    return {
        "range": {"start": iso(start), "end": iso(end)},
        "accounts": sections,
        "note": DELAY_NOTE + " Missing values are shown as unavailable. Fixture readings are labeled and never added to live readings.",
    }
