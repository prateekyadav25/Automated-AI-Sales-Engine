"""Publish approved, due creatives through the official Meta flows.

Order of checks: feature flag, slot and creative state, strategy, account and
token, emergency stop and social pause, daily caps, execution authorization,
the demonstration guard, the deployment publish mode, and public media. The
effect is recorded before the provider call. Instagram container ids and
Facebook upload ids are stored the moment Meta returns them, so a retry reuses
them. An unknown result is reconciled against the account before anything is
sent again. Rate limits back off. A refused token moves the account to
needs_reconnect.
"""

from __future__ import annotations

import re
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.autonomy import AutonomousRun
from app.models.growth import (
    GrowthAccount,
    GrowthAsset,
    GrowthCalendarItem,
    GrowthCreative,
    GrowthMedia,
    GrowthPublication,
)
from app.providers.meta_growth import GraphResult, MetaGrowthClient
from app.services.audit import emit_event, write_audit
from app.services.autopilot_settings import get_or_create_settings
from app.services.demo_guard import external_execution_block
from app.services.effects import EffectAttempt, ReconciledEffect, execute_external_effect
from app.services.growth.acceptance import acceptance_step, require_authorized
from app.services.growth.accounts import live_client, mark_auth_failure, token_problem
from app.services.growth.assets import asset_bytes, creative_assets, public_ready
from app.services.growth.common import aware, digest, dumps, growth_enabled, iso, loads, now, publish_mode
from app.services.growth.governance import ACTION, publish_authorization, published_last_day, request_publish_approval
from app.services.growth.planner import owned_item, strategy_for

LATE_GRACE = timedelta(hours=6)
RETRY_RATE_LIMIT = 900
RETRY_PROCESSING = 60


def final_caption(creative: GrowthCreative) -> str:
    tags = " ".join(f"#{tag}" for tag in loads(creative.hashtags_json, []))
    return f"{creative.caption}\n\n{tags}".strip() if tags else creative.caption


def _caption_key(text: str) -> str:
    return digest(re.sub(r"\s+", " ", (text or "").strip().casefold())[:300])


def _channel_block(db: Session, tenant_id: UUID) -> str:
    if get_settings().global_emergency_stop:
        return "Global emergency stop is active. External actions are suspended."
    settings = get_or_create_settings(db, tenant_id=tenant_id)
    if settings.emergency_stop:
        return "Emergency stop is active. External actions are suspended."
    if settings.social_channel_paused:
        return "Social channel is paused."
    return ""


def _attempt_for(result: GraphResult, *, unknown_is_ambiguous: bool) -> EffectAttempt:
    if result.failure_class in {"RATE_LIMIT", "PUBLISH_LIMIT"}:
        delay = result.retry_after_seconds or (3600 if result.failure_class == "PUBLISH_LIMIT" else RETRY_RATE_LIMIT)
        return EffectAttempt(failed=True, retryable=True, failure_class=result.failure_class, retry_after_seconds=delay)
    if result.unknown_effect:
        if unknown_is_ambiguous:
            return EffectAttempt()
        return EffectAttempt(failed=True, retryable=True, failure_class=result.failure_class, retry_after_seconds=RETRY_PROCESSING)
    return EffectAttempt(failed=True, retryable=False, failure_class=result.failure_class or "INVALID")


def _remember_error(publication: GrowthPublication, result: GraphResult) -> None:
    publication.failure_class = result.failure_class
    publication.last_error = result.error_message[:1000]


def _confirm(db: Session, publication: GrowthPublication, graph: MetaGrowthClient, external_id: str) -> EffectAttempt:
    publication.external_id = external_id
    details = graph.media_details(external_id) if publication.platform == "instagram" else graph.post_details(external_id)
    if details.ok:
        publication.permalink = str(details.data.get("permalink") or details.data.get("permalink_url") or "")[:1000]
    publication.status = "published"
    publication.published_at = now()
    publication.failure_class = ""
    publication.last_error = ""
    db.flush()
    return EffectAttempt(accepted=True, provider_id=external_id)


def _instagram(db: Session, publication: GrowthPublication, account: GrowthAccount, creative: GrowthCreative, assets: list[GrowthAsset], graph: MetaGrowthClient) -> EffectAttempt:
    caption = final_caption(creative)
    if not publication.container_id:
        if creative.format == "image":
            image = next(asset for asset in assets if asset.role == "image")
            created = graph.ig_image_container(account.external_id, image_url=image.public_url, caption=caption)
        elif creative.format == "carousel":
            children = loads(publication.child_container_ids, [])
            slides = sorted((asset for asset in assets if asset.role == "slide"), key=lambda asset: asset.position)
            for slide in slides[len(children) :]:
                child = graph.ig_image_container(account.external_id, image_url=slide.public_url, carousel_item=True)
                if not child.ok or not str(child.data.get("id") or ""):
                    _remember_error(publication, child)
                    return _attempt_for(child, unknown_is_ambiguous=False)
                children.append(str(child.data["id"]))
                publication.child_container_ids = dumps(children)
                db.flush()
            created = graph.ig_carousel_container(account.external_id, children=children, caption=caption)
        elif creative.format == "reel":
            video = next(asset for asset in assets if asset.role == "reel")
            cover = next((asset for asset in assets if asset.role == "cover"), None)
            created = graph.ig_reel_container(account.external_id, video_url=video.public_url, caption=caption, cover_url=cover.public_url if cover is not None else "")
        else:
            return EffectAttempt(failed=True, failure_class="UNSUPPORTED")
        if not created.ok or not str(created.data.get("id") or ""):
            _remember_error(publication, created)
            return _attempt_for(created, unknown_is_ambiguous=False)
        publication.container_id = str(created.data["id"])
        publication.status = "container_created"
        db.flush()
    status = graph.ig_container_status(publication.container_id)
    if not status.ok:
        _remember_error(publication, status)
        return _attempt_for(status, unknown_is_ambiguous=False)
    code = str(status.data.get("status_code") or "").upper()
    if code == "IN_PROGRESS":
        publication.status = "processing"
        return EffectAttempt(failed=True, retryable=True, failure_class="PROCESSING", retry_after_seconds=RETRY_PROCESSING)
    if code == "EXPIRED":
        publication.container_id = ""
        publication.child_container_ids = "[]"
        publication.status = "requested"
        publication.last_error = "The container expired before publishing. A new container will be created."
        return EffectAttempt(failed=True, retryable=True, failure_class="EXPIRED", retry_after_seconds=RETRY_PROCESSING)
    if code == "ERROR":
        publication.last_error = str(status.data.get("status") or "Meta could not process the media.")[:1000]
        publication.failure_class = "MEDIA"
        return EffectAttempt(failed=True, retryable=False, failure_class="MEDIA")
    if code == "PUBLISHED":
        return EffectAttempt()
    if code not in {"FINISHED", ""}:
        return EffectAttempt()
    quota = graph.ig_publishing_limit(account.external_id)
    if quota.ok:
        entries = quota.data.get("data") if isinstance(quota.data.get("data"), list) else []
        first = entries[0] if entries and isinstance(entries[0], dict) else {}
        used = first.get("quota_usage")
        total = (first.get("config") or {}).get("quota_total") if isinstance(first.get("config"), dict) else None
        if isinstance(used, int) and isinstance(total, int) and used >= total:
            publication.last_error = f"Instagram publishing limit reached ({used} of {total} in 24 hours)."
            return EffectAttempt(failed=True, retryable=True, failure_class="PUBLISH_LIMIT", retry_after_seconds=3600)
    published = graph.ig_publish(account.external_id, creation_id=publication.container_id)
    if not published.ok or not str(published.data.get("id") or ""):
        _remember_error(publication, published)
        return _attempt_for(published, unknown_is_ambiguous=True)
    return _confirm(db, publication, graph, str(published.data["id"]))


def _facebook(db: Session, publication: GrowthPublication, account: GrowthAccount, creative: GrowthCreative, assets: list[GrowthAsset], graph: MetaGrowthClient) -> EffectAttempt:
    caption = final_caption(creative)
    page = account.external_id
    if creative.format == "image":
        image = next(asset for asset in assets if asset.role == "image")
        result = graph.fb_photo(page, image=asset_bytes(image), caption=caption)
        if not result.ok:
            _remember_error(publication, result)
            return _attempt_for(result, unknown_is_ambiguous=True)
        external = str(result.data.get("post_id") or result.data.get("id") or "")
        return _confirm(db, publication, graph, external) if external else EffectAttempt()
    if creative.format == "carousel":
        uploaded = loads(publication.child_container_ids, [])
        slides = sorted((asset for asset in assets if asset.role == "slide"), key=lambda asset: asset.position)
        for slide in slides[len(uploaded) :]:
            photo = graph.fb_photo(page, image=asset_bytes(slide), caption="", published=False)
            if not photo.ok or not str(photo.data.get("id") or ""):
                _remember_error(publication, photo)
                return _attempt_for(photo, unknown_is_ambiguous=False)
            uploaded.append(str(photo.data["id"]))
            publication.child_container_ids = dumps(uploaded)
            db.flush()
        result = graph.fb_feed(page, message=caption, media_fbids=uploaded)
        if not result.ok or not str(result.data.get("id") or ""):
            _remember_error(publication, result)
            return _attempt_for(result, unknown_is_ambiguous=True)
        return _confirm(db, publication, graph, str(result.data["id"]))
    if creative.format == "text":
        result = graph.fb_feed(page, message=caption, link=creative.link_url if creative.link_url.startswith("https://") else "")
        if not result.ok or not str(result.data.get("id") or ""):
            _remember_error(publication, result)
            return _attempt_for(result, unknown_is_ambiguous=True)
        return _confirm(db, publication, graph, str(result.data["id"]))
    if creative.format == "reel":
        if not publication.upload_id:
            started = graph.fb_reel_start(page)
            if not started.ok or not str(started.data.get("video_id") or ""):
                _remember_error(publication, started)
                return _attempt_for(started, unknown_is_ambiguous=False)
            publication.upload_id = str(started.data["video_id"])
            db.flush()
            video = next(asset for asset in assets if asset.role == "reel")
            uploaded = graph.upload_reel_bytes(publication.upload_id, asset_bytes(video))
            if not uploaded.ok:
                publication.upload_id = ""
                _remember_error(publication, uploaded)
                return _attempt_for(uploaded, unknown_is_ambiguous=False)
            finished = graph.fb_reel_finish(page, video_id=publication.upload_id, description=caption, title=creative.title[:100])
            if not finished.ok:
                _remember_error(publication, finished)
                return _attempt_for(finished, unknown_is_ambiguous=True)
            publication.status = "processing"
            db.flush()
        status = graph.fb_video_status(publication.upload_id)
        if not status.ok:
            _remember_error(publication, status)
            return _attempt_for(status, unknown_is_ambiguous=False)
        state = status.data.get("status") if isinstance(status.data.get("status"), dict) else {}
        post_id = str(status.data.get("post_id") or "")
        video_status = str(state.get("video_status") or "").lower()
        if video_status == "error":
            publication.last_error = "Meta could not process the reel."
            return EffectAttempt(failed=True, retryable=False, failure_class="MEDIA")
        if not post_id:
            publication.status = "processing"
            return EffectAttempt(failed=True, retryable=True, failure_class="PROCESSING", retry_after_seconds=RETRY_PROCESSING)
        return _confirm(db, publication, graph, post_id)
    return EffectAttempt(failed=True, failure_class="UNSUPPORTED")


def _reconcile(db: Session, publication: GrowthPublication, account: GrowthAccount, creative: GrowthCreative, graph: MetaGrowthClient) -> ReconciledEffect:
    """Look for the post before trying again. No evidence means the effect stays unknown."""
    if publication.external_id:
        return ReconciledEffect("confirmed", publication.external_id)
    wanted = _caption_key(final_caption(creative))
    if account.platform == "instagram":
        if publication.container_id:
            status = graph.ig_container_status(publication.container_id)
            code = str(status.data.get("status_code") or "").upper() if status.ok else ""
            if code == "FINISHED":
                return ReconciledEffect("retry_wait")
            if code in {"ERROR", "EXPIRED"}:
                return ReconciledEffect("retry_wait") if code == "EXPIRED" else ReconciledEffect("confirmed_failure")
        recent = graph.instagram_media(account.external_id, limit=10)
    else:
        if publication.upload_id:
            status = graph.fb_video_status(publication.upload_id)
            post_id = str(status.data.get("post_id") or "") if status.ok else ""
            if post_id:
                _confirm(db, publication, graph, post_id)
                return ReconciledEffect("confirmed", post_id)
        recent = graph.page_posts(account.external_id, limit=10)
    if not recent.ok:
        return ReconciledEffect("unknown")
    for media in recent.data.get("data") or []:
        if isinstance(media, dict) and _caption_key(str(media.get("caption") or media.get("message") or "")) == wanted:
            external = str(media.get("id") or "")
            if external:
                _confirm(db, publication, graph, external)
                return ReconciledEffect("confirmed", external)
    return ReconciledEffect("unknown")


def _publication(db: Session, tenant_id: UUID, item: GrowthCalendarItem, creative: GrowthCreative, account: GrowthAccount, provenance: str) -> GrowthPublication:
    row = db.scalar(
        select(GrowthPublication).where(
            GrowthPublication.tenant_id == tenant_id,
            GrowthPublication.calendar_item_id == item.id,
            GrowthPublication.creative_id == creative.id,
        )
    )
    if row is None:
        row = GrowthPublication(
            tenant_id=tenant_id,
            calendar_item_id=item.id,
            creative_id=creative.id,
            account_id=account.id,
            platform=account.platform,
            format=creative.format,
            caption_hash=_caption_key(final_caption(creative)),
            provenance=provenance,
        )
        db.add(row)
        db.flush()
    item.publication_id = row.id
    return row


def _record_media(db: Session, publication: GrowthPublication, item: GrowthCalendarItem, creative: GrowthCreative) -> None:
    media = db.scalar(select(GrowthMedia).where(GrowthMedia.tenant_id == publication.tenant_id, GrowthMedia.account_id == publication.account_id, GrowthMedia.external_id == publication.external_id))
    if media is None:
        media = GrowthMedia(tenant_id=publication.tenant_id, account_id=publication.account_id, external_id=publication.external_id)
        db.add(media)
    media.origin = "engine"
    media.publication_id = publication.id
    media.caption = final_caption(creative)[:5000]
    media.permalink = publication.permalink
    media.posted_at = publication.published_at
    media.retrieved_at = now()
    media.provenance = publication.provenance
    media.pillar_key = item.pillar_key
    media.format = creative.format
    media.media_product_type = "REELS" if creative.format == "reel" else "FEED"
    db.flush()


def publish_item(db: Session, *, tenant_id: UUID, actor_id: UUID | None, item_id: UUID, client: MetaGrowthClient | None = None, provenance: str = "live") -> dict:
    item = owned_item(db, tenant_id, item_id)

    def stop(message: str, *, status: str | None = None) -> dict:
        if status:
            item.status = status
        item.blocker = message
        db.flush()
        return {"status": item.status, "detail": message, "published": False}

    if not growth_enabled(db, tenant_id):
        return stop("ENABLE_SOCIAL_GROWTH is off for this workspace. Nothing was published.")
    if item.status not in {"scheduled", "publishing"}:
        return stop(f"This slot is {item.status}. Only a scheduled slot publishes.")
    creative = db.get(GrowthCreative, item.creative_id) if item.creative_id else None
    if creative is None or creative.tenant_id != tenant_id or creative.status != "approved" or creative.quality_state != "passed":
        return stop("The creative is not approved or did not pass quality checks.", status="blocked")
    assets = creative_assets(db, tenant_id, creative.id)
    if digest(creative.caption, creative.hashtags_json, *sorted(asset.sha256 for asset in assets)) != creative.content_hash:
        return stop("The creative changed after approval. It must be approved again.", status="blocked")
    strategy = strategy_for(db, item)
    if strategy is None or strategy.status != "approved":
        return stop("The strategy is not approved or is paused.")
    account = db.get(GrowthAccount, item.account_id)
    if account is None or account.tenant_id != tenant_id:
        return stop("The account is missing.", status="blocked")
    problem = token_problem(account)
    if problem:
        return stop(problem, status="blocked")
    if account.provenance == "fixture" and client is None:
        return stop("A fixture account never reaches Meta. Nothing was published.", status="blocked")
    blocked = _channel_block(db, tenant_id)
    if blocked:
        return stop(blocked)
    if published_last_day(db, tenant_id, account_id=account.id) >= max(account.daily_cap, 0):
        return stop(f"The daily cap of {account.daily_cap} post(s) for this account is reached. It will wait.")
    if account.platform == "instagram" and published_last_day(db, tenant_id, account_id=account.id) >= get_settings().social_growth_instagram_daily_limit:
        return stop("The Instagram 24-hour publishing limit is reached. It will wait.")
    decision, reason, reference = publish_authorization(db, tenant_id, item, creative, account)
    if decision != "execute":
        request_publish_approval(db, tenant_id=tenant_id, actor_id=actor_id, item=item, creative=creative, account=account)
        return stop(reason)
    guard = external_execution_block(db, tenant_id=tenant_id, action="social.publish", target_id=str(item.id), channel=account.platform, real_effect=True)
    if guard:
        return stop(guard)
    recorded = provenance
    owned = False
    graph = client
    if graph is None:
        if publish_mode() != "live":
            return stop("Publishing is disabled in this deployment (SOCIAL_GROWTH_PUBLISH_MODE). Nothing was published.")
        denied = require_authorized(db, tenant_id, acceptance_step(account.platform, creative.format))
        if denied:
            return stop(denied)
        graph = live_client(db, account)
        owned = True
        recorded = "provider"
        if graph is None:
            mark_auth_failure(account, "No stored token. Reconnect the account.")
            return stop(account.last_error, status="blocked")
    try:
        if account.platform == "instagram":
            unready = [asset.role for asset in assets if asset.role in {"image", "slide", "reel", "cover"} and not public_ready(asset.public_url)]
            if unready:
                return stop("Instagram fetches media from a public https address. PUBLIC_API_BASE_URL is not public, so nothing was sent.")
        publication = _publication(db, tenant_id, item, creative, account, recorded)
        publication.api_version = graph.version
        publication.attempts += 1
        item.status = "publishing"
        run = AutonomousRun(
            tenant_id=tenant_id,
            created_by=actor_id,
            status="running",
            trigger="schedule" if actor_id is None else "manual",
            workflow="social_growth",
            trigger_event=f"growth:{item.id}"[:80],
            summary=f"Publish {creative.format} to {account.platform}",
        )
        db.add(run)
        db.flush()
        handler = _instagram if account.platform == "instagram" else _facebook

        def call() -> EffectAttempt:
            return handler(db, publication, account, creative, assets, graph)

        def reconcile(_effect) -> ReconciledEffect:
            return _reconcile(db, publication, account, creative, graph)

        effect = execute_external_effect(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            run=run,
            action=ACTION,
            channel=account.platform,
            target_id=str(item.id),
            content_version=f"{creative.content_hash}:{publication.epoch}",
            grant_id=reference,
            call=call,
            reconcile=reconcile,
        )
        publication.effect_key = effect.effect_key
        outcome = effect.outcome
        if outcome == "confirmed":
            if not publication.external_id:
                publication.external_id = effect.provider_ref
                publication.status = "published"
                publication.published_at = publication.published_at or now()
            item.status = "published"
            item.blocker = ""
            run.status = "completed"
            run.finished_at = now()
            _record_media(db, publication, item, creative)
            write_audit(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="growth.published",
                entity_type="growth_publication",
                entity_id=str(publication.id),
                after={"external_id": publication.external_id, "permalink": publication.permalink, "provenance": provenance, "authorization": reference},
                actor_type="human" if actor_id else "ai",
            )
            emit_event(db, tenant_id=tenant_id, event_type="social_growth.published", entity_type="growth_publication", entity_id=str(publication.id), payload={"platform": account.platform})
            return {"status": "published", "detail": "Published. The provider id and permalink are stored.", "published": True, "external_id": publication.external_id, "permalink": publication.permalink}
        if outcome == "confirmed_failure":
            publication.status = "failed"
            if publication.failure_class == "AUTH":
                mark_auth_failure(account, publication.last_error)
            run.status = "blocked"
            run.finished_at = now()
            return stop(publication.last_error or "Meta refused the post.", status="failed")
        if outcome == "retry_wait":
            meta = loads(effect.detail, {})
            publication.status = "processing" if meta.get("failure_class") in {"PROCESSING", "EXPIRED"} else "rate_limited"
            publication.next_attempt_at = now() + timedelta(seconds=int(meta.get("retry_after_seconds") or RETRY_PROCESSING))
            return stop(f"Waiting before the next attempt ({meta.get('failure_class') or 'retry'}). Nothing was sent twice.", status="publishing")
        publication.status = "unknown"
        return stop("The result is unknown. The account is checked before any retry.", status="publishing")
    finally:
        if owned:
            graph.close()


def due_items(db: Session, tenant_id: UUID) -> list[GrowthCalendarItem]:
    moment = now()
    rows = db.scalars(
        select(GrowthCalendarItem).where(
            GrowthCalendarItem.tenant_id == tenant_id,
            GrowthCalendarItem.deleted_at.is_(None),
            GrowthCalendarItem.status.in_(["scheduled", "publishing"]),
            GrowthCalendarItem.planned_for <= moment,
        )
    ).all()
    due: list[GrowthCalendarItem] = []
    for row in rows:
        planned = aware(row.planned_for) or moment
        if row.status == "scheduled" and moment - planned > LATE_GRACE:
            row.status = "blocked"
            row.blocker = "The planned time passed more than six hours ago. Reschedule it so it is not posted out of its window."
            continue
        if row.publication_id is not None:
            publication = db.get(GrowthPublication, row.publication_id)
            if publication is not None and aware(publication.next_attempt_at) is not None and aware(publication.next_attempt_at) > moment:
                continue
        due.append(row)
    return due


def publish_due(db: Session, *, tenant_id: UUID) -> int:
    """Worker entry. In a disabled deployment nothing is attempted and nothing is marked."""
    if publish_mode() != "live" or not growth_enabled(db, tenant_id):
        return 0
    published = 0
    for row in due_items(db, tenant_id):
        result = publish_item(db, tenant_id=tenant_id, actor_id=None, item_id=row.id)
        published += 1 if result.get("published") else 0
    return published


def resolve_unknown(db: Session, *, tenant_id: UUID, actor_id: UUID, publication_id: UUID, decision: str, external_id: str = "", note: str = "") -> dict:
    """An operator who checked the account confirms what happened. Not published allows a new attempt."""
    row = db.scalar(select(GrowthPublication).where(GrowthPublication.tenant_id == tenant_id, GrowthPublication.id == publication_id, GrowthPublication.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    if row.status not in {"unknown", "failed"}:
        raise HTTPException(status_code=409, detail=f"This publication is {row.status}.")
    item = db.get(GrowthCalendarItem, row.calendar_item_id)
    creative = db.get(GrowthCreative, row.creative_id)
    before = row.status
    if decision == "published":
        if not re.fullmatch(r"[0-9_]{3,120}", external_id.strip()):
            raise HTTPException(status_code=422, detail="Give the post id shown by Meta for this post.")
        row.external_id = external_id.strip()
        row.status = "published"
        row.published_at = row.published_at or now()
        row.last_error = f"Confirmed by an operator: {note.strip()}"[:1000]
        if item is not None and creative is not None:
            item.status = "published"
            _record_media(db, row, item, creative)
    elif decision == "not_published":
        row.epoch += 1
        row.status = "requested"
        row.container_id = ""
        row.child_container_ids = "[]"
        row.upload_id = ""
        row.last_error = f"An operator confirmed nothing was posted: {note.strip()}"[:1000]
        if item is not None:
            item.status = "scheduled"
            item.blocker = "Cleared for a new attempt after an operator checked the account."
    else:
        raise HTTPException(status_code=422, detail="Decision must be published or not_published.")
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.publication_resolve", entity_type="growth_publication", entity_id=str(row.id), before={"status": before}, after={"status": row.status, "decision": decision, "external_id": row.external_id})
    return publication_out(row)


def publication_out(row: GrowthPublication) -> dict:
    return {
        "id": str(row.id),
        "item_id": str(row.calendar_item_id),
        "creative_id": str(row.creative_id),
        "account_id": str(row.account_id),
        "platform": row.platform,
        "format": row.format,
        "status": row.status,
        "container_id": row.container_id,
        "external_id": row.external_id,
        "permalink": row.permalink,
        "published_at": iso(row.published_at),
        "attempts": row.attempts,
        "failure_class": row.failure_class,
        "last_error": row.last_error,
        "next_attempt_at": iso(row.next_attempt_at),
        "api_version": row.api_version,
        "provenance": row.provenance,
    }
