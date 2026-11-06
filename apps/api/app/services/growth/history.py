"""Historical posts from authorized accounts, and public competitor benchmarks.

History is read from the account's own media list. Competitor figures come
from Instagram Business Discovery for business or creator accounts only.
Hidden or omitted counts stay null. Averages use only the values returned.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.growth import CompetitorBenchmark, GrowthAccount, GrowthMedia
from app.providers.meta_growth import MetaGrowthClient
from app.services.audit import write_audit
from app.services.growth.acceptance import require_authorized
from app.services.growth.accounts import live_client, live_read_block, mark_auth_failure, owned_account, token_problem
from app.services.growth.brand import ensure_profile, record_source, remember_fact
from app.services.growth.brand_extract import Finding, hashtags, voice_profile
from app.services.growth.common import dumps, loads, now

_USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def parse_meta_time(value: str) -> datetime | None:
    raw = (value or "").strip()
    for pattern in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


def _open(db: Session, tenant_id: UUID, account: GrowthAccount, client: MetaGrowthClient | None) -> tuple[MetaGrowthClient | None, bool, str]:
    if client is not None:
        return client, False, ""
    if account.provenance == "fixture":
        return None, False, "Fixture accounts have no Meta history to read."
    blocked = live_read_block(db, tenant_id)
    if blocked:
        return None, False, blocked
    denied = require_authorized(db, tenant_id, "history_import")
    if denied:
        return None, False, denied
    problem = token_problem(account)
    if problem:
        return None, False, problem
    live = live_client(db, account)
    if live is None:
        return None, False, "No stored token. Reconnect the account."
    return live, True, ""


def import_history(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    account_id: UUID,
    client: MetaGrowthClient | None = None,
    provenance: str = "live",
    max_items: int = 100,
) -> dict:
    account = owned_account(db, tenant_id, account_id)
    graph, owned, blocked = _open(db, tenant_id, account, client)
    if graph is None:
        return {"status": "blocked", "imported": 0, "detail": blocked}
    recorded = "provider" if owned else provenance
    try:
        imported = 0
        after = ""
        captions: list[str] = []
        while imported < max_items:
            if account.platform == "instagram":
                result = graph.instagram_media(account.external_id, limit=min(50, max_items - imported), after=after)
            else:
                result = graph.page_posts(account.external_id, limit=min(50, max_items - imported), after=after)
            if not result.ok:
                if result.failure_class == "AUTH":
                    mark_auth_failure(account, result.error_message)
                return {"status": "failed", "imported": imported, "detail": result.error_message}
            rows = result.data.get("data") if isinstance(result.data.get("data"), list) else []
            for item in rows:
                if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                    continue
                caption = str(item.get("caption") or item.get("message") or "")
                captions.append(caption)
                _remember_media(db, tenant_id=tenant_id, actor_id=actor_id, account=account, item=item, caption=caption, provenance=recorded)
                imported += 1
            paging = result.data.get("paging") if isinstance(result.data.get("paging"), dict) else {}
            after = str(((paging.get("cursors") or {}) if isinstance(paging.get("cursors"), dict) else {}).get("after") or "")
            if not rows or not after or not paging.get("next"):
                break
        profile = ensure_profile(db, tenant_id, actor_id)
        handle = account.username or account.name or account.external_id
        source = record_source(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            profile=profile,
            kind="social_account",
            url=f"meta:{account.platform}:{account.external_id}",
            result=None,
            title=f"{account.platform.title()} {handle}",
            excerpt=f"{imported} post(s) read from the account media list.",
            provenance=provenance,
        )
        for tag, count in hashtags(captions):
            remember_fact(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                profile=profile,
                finding=Finding("theme", f"#{tag}", tag, f"Used in {count} past {account.platform} caption(s).", 65),
                source=source,
                method="provider",
            )
        voice = loads(profile.voice_json, {})
        voice[f"{account.platform}_captions"] = voice_profile(captions) | {"source_id": str(source.id), "posts": len(captions)}
        profile.voice_json = dumps(voice)
        write_audit(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="growth.history_import",
            entity_type="growth_account",
            entity_id=str(account.id),
            after={"imported": imported, "provenance": provenance},
            actor_type="human" if actor_id else "ai",
        )
        return {"status": "imported", "imported": imported, "detail": f"Read {imported} existing post(s). Metrics are read separately and are never estimated."}
    finally:
        if owned:
            graph.close()


def _remember_media(db: Session, *, tenant_id: UUID, actor_id: UUID | None, account: GrowthAccount, item: dict, caption: str, provenance: str) -> GrowthMedia:
    external_id = str(item.get("id"))
    row = db.scalar(
        select(GrowthMedia).where(
            GrowthMedia.tenant_id == tenant_id,
            GrowthMedia.account_id == account.id,
            GrowthMedia.external_id == external_id,
        )
    )
    if row is None:
        row = GrowthMedia(tenant_id=tenant_id, created_by=actor_id, account_id=account.id, external_id=external_id, origin="historical")
        db.add(row)
    product_type = str(item.get("media_product_type") or "").upper()
    media_type = str(item.get("media_type") or ("POST" if account.platform == "facebook" else "")).upper()
    row.caption = caption[:5000]
    row.permalink = str(item.get("permalink") or item.get("permalink_url") or row.permalink)[:1000]
    row.posted_at = parse_meta_time(str(item.get("timestamp") or item.get("created_time") or "")) or row.posted_at
    row.media_type = media_type[:32]
    row.media_product_type = product_type[:32]
    row.retrieved_at = now()
    row.provenance = provenance
    if not row.format:
        row.format = "reel" if product_type == "REELS" else "carousel" if media_type == "CAROUSEL_ALBUM" else "image" if media_type == "IMAGE" else "text" if account.platform == "facebook" else ""
    db.flush()
    return row


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def save_competitors(db: Session, *, tenant_id: UUID, actor_id: UUID | None, usernames: list[str]) -> dict:
    profile = ensure_profile(db, tenant_id, actor_id)
    cleaned = list(dict.fromkeys(name.strip().lstrip("@") for name in usernames if name.strip()))
    invalid = [name for name in cleaned if not _USERNAME.match(name)]
    if invalid:
        return {"status": "blocked", "detail": f"Not an Instagram username: {', '.join(invalid[:3])}."}
    profile.competitor_usernames = dumps(cleaned[:10])
    for name in cleaned[:10]:
        if db.scalar(select(CompetitorBenchmark).where(CompetitorBenchmark.tenant_id == tenant_id, CompetitorBenchmark.platform == "instagram", CompetitorBenchmark.username == name)) is None:
            db.add(CompetitorBenchmark(tenant_id=tenant_id, created_by=actor_id, platform="instagram", username=name, status="not_read"))
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.competitors_save", entity_type="brand_profile", entity_id=str(profile.id), after={"usernames": cleaned[:10]})
    return {"status": "saved", "detail": "Usernames saved. Figures are read only from Business Discovery when live reads are allowed."}


def refresh_competitors(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    usernames: list[str] | None = None,
    client: MetaGrowthClient | None = None,
    provenance: str = "live",
) -> dict:
    if usernames is not None:
        saved = save_competitors(db, tenant_id=tenant_id, actor_id=actor_id, usernames=usernames)
        if saved["status"] == "blocked":
            return {**saved, "competitors": []}
    profile = ensure_profile(db, tenant_id, actor_id)
    names = loads(profile.competitor_usernames, [])
    rows = list(db.scalars(select(CompetitorBenchmark).where(CompetitorBenchmark.tenant_id == tenant_id, CompetitorBenchmark.deleted_at.is_(None), CompetitorBenchmark.username.in_(names))).all())
    own = db.scalar(
        select(GrowthAccount).where(
            GrowthAccount.tenant_id == tenant_id,
            GrowthAccount.platform == "instagram",
            GrowthAccount.provenance == "live",
            GrowthAccount.status.in_(["connected", "unverified"]),
            GrowthAccount.deleted_at.is_(None),
        )
    )
    if not rows:
        return {"status": "empty", "detail": "No competitor usernames are saved.", "competitors": []}
    if own is None and client is None:
        for row in rows:
            row.status = "unavailable"
            row.error = "Connect an Instagram professional account. Business Discovery is read through it."
        return {"status": "blocked", "detail": rows[0].error, "competitors": rows}
    graph, owned, blocked = (client, False, "") if client is not None else _open(db, tenant_id, own, None)
    if graph is None:
        return {"status": "blocked", "detail": blocked, "competitors": rows}
    ig_id = own.external_id if own is not None else "0"
    try:
        for row in rows:
            result = graph.ig_business_discovery(ig_id, row.username)
            row.retrieved_at = now()
            row.provenance = provenance
            row.source = "instagram.business_discovery"
            if not result.ok:
                row.status = "failed" if result.failure_class != "INVALID" else "unsupported"
                row.error = result.error_message
                continue
            found = result.data.get("business_discovery") if isinstance(result.data.get("business_discovery"), dict) else None
            if found is None:
                row.status = "unavailable"
                row.error = "Meta returned no business account for this username."
                continue
            row.followers_count = found.get("followers_count") if isinstance(found.get("followers_count"), int) else None
            row.media_count = found.get("media_count") if isinstance(found.get("media_count"), int) else None
            media = (found.get("media") or {}).get("data") if isinstance(found.get("media"), dict) else []
            items = [item for item in media or [] if isinstance(item, dict)]
            likes = [item["like_count"] for item in items if isinstance(item.get("like_count"), int)]
            comments = [item["comments_count"] for item in items if isinstance(item.get("comments_count"), int)]
            stamps = sorted(moment for moment in (parse_meta_time(str(item.get("timestamp") or "")) for item in items) if moment is not None)
            row.sample_size = len(items)
            row.avg_likes = _decimal(sum(likes) / len(likes)) if likes else None
            row.avg_comments = _decimal(sum(comments) / len(comments)) if comments else None
            span_days = (stamps[-1] - stamps[0]).total_seconds() / 86400 if len(stamps) >= 2 else 0
            row.posts_per_week = _decimal((len(stamps) - 1) / span_days * 7) if span_days > 0 else None
            row.status = "recorded"
            row.error = "" if likes else "Like counts were not returned. Averages use only returned values."
        write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.competitors_refresh", entity_type="brand_profile", entity_id=str(profile.id), after={"usernames": names, "provenance": provenance}, actor_type="human" if actor_id else "ai")
        return {"status": "recorded", "detail": "Competitor figures are the values Meta returned at the retrieval time.", "competitors": rows}
    finally:
        if owned:
            graph.close()
