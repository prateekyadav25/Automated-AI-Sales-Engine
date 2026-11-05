"""Creative production, review, and scheduling for one calendar item.

Copy comes from approved facts. Images and carousels are branded templates.
Reels are FFmpeg renders checked by ffprobe. Every asset carries a quality
report. Unsupported claims, sensitive terms, repetition risk, or a failed
check send the creative to a person. Policy approval happens only when the
approved strategy allows automatic scheduling, an execution grant covers the
platform, and nothing needs review.
"""

from __future__ import annotations

from io import BytesIO
from uuid import UUID

import httpx
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.providers import LLMProvider
from app.core.config import get_settings
from app.models.content import SellerProfile
from app.models.growth import BrandFact, BrandProfile, GrowthAccount, GrowthAsset, GrowthCalendarItem, GrowthCreative
from app.providers.image_generation import generate_background
from app.services.audit import emit_event, write_audit
from app.services.growth.assets import asset_bytes, asset_out, creative_assets, store_asset
from app.services.growth.attribution import ensure_tracking_link, short_link
from app.services.growth.brand import approved_facts
from app.services.growth.claims import check_claims
from app.services.growth.common import digest, dumps, iso, loads, now
from app.services.growth.copywriter import write_caption
from app.services.growth.governance import active_grant, publish_authorization, request_publish_approval
from app.services.growth.planner import owned_item, strategy_for
from app.services.growth.quality import check_caption, check_carousel, check_image
from app.services.growth.render import (
    SIZES,
    BrandKit,
    RenderUnavailable,
    jpeg_bytes,
    load_logo,
    render_card,
    resolve_fonts,
)
from app.services.growth.video import VideoUnavailable, build_reel, check_reel
from app.services.provider_resolve import resolve_channel

FRAME_SECONDS = 3.5
OPEN_ITEM = ("planned", "creative_ready", "needs_review", "blocked")


def brand_kit(db: Session, tenant_id: UUID) -> BrandKit:
    regular, bold = resolve_fonts()
    profile = db.scalar(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id, BrandProfile.deleted_at.is_(None)))
    seller = db.scalar(select(SellerProfile).where(SellerProfile.tenant_id == tenant_id, SellerProfile.deleted_at.is_(None)))
    approved_colors = [fact.value for fact in approved_facts(db, tenant_id, ("color",)) if fact.value.startswith("#")]
    notes: list[str] = []
    colors = list(dict.fromkeys(approved_colors))
    if not colors:
        notes.append("No approved brand colour is stored. A neutral palette was used and the creative needs review.")
    logo = None
    if profile is not None and profile.logo_asset_id is not None:
        row = db.get(GrowthAsset, profile.logo_asset_id)
        if row is not None and row.tenant_id == tenant_id:
            try:
                logo = load_logo(asset_bytes(row))
            except Exception:  # noqa: BLE001 - a missing logo object leaves the card without a logo
                logo = None
    name = (profile.company_name if profile is not None else "") or (seller.company_name if seller is not None else "")
    return BrandKit(name=name, colors=colors, regular_font=regular, bold_font=bold, logo=logo, notes=notes)


def _brief_facts(db: Session, tenant_id: UUID, item: GrowthCalendarItem) -> tuple[list[dict], list[str]]:
    wanted = [str(fact.get("id")) for fact in loads(item.brief_json, {}).get("facts") or []]
    rows = {str(row.id): row for row in db.scalars(select(BrandFact).where(BrandFact.tenant_id == tenant_id, BrandFact.id.in_([UUID(x) for x in wanted if x]))).all()} if wanted else {}
    facts: list[dict] = []
    missing: list[str] = []
    for fact_id in wanted:
        row = rows.get(fact_id)
        if row is None or row.state != "approved" or row.deleted_at is not None:
            missing.append(fact_id)
            continue
        facts.append({"id": fact_id, "category": row.category, "statement": row.statement, "value": row.value, "source_url": row.source_url})
    return facts, missing


def _background(db: Session, tenant_id: UUID, kit: BrandKit, pillar: str, image_client) -> tuple[Image.Image | None, str, str]:
    settings = get_settings()
    if image_client is None and not settings.gemini_image_model:
        return None, "", ""
    resolved = resolve_channel(db, tenant_id, "gemini")
    api_key = resolved.secrets.get("access_token") or settings.gemini_api_key
    client = image_client or httpx.Client(timeout=90.0)
    try:
        prompt = (
            f"Abstract photographic background for a social post about {pillar}. "
            f"Colour palette {', '.join(kit.colors[:3]) or 'neutral blues'}. No text, no letters, no logos, no people, no products."
        )
        result = generate_background(client, api_key=api_key, model=settings.gemini_image_model or "image-model", prompt=prompt)
    finally:
        if image_client is None:
            client.close()
    if not result.ok:
        return None, "", result.reason
    try:
        with Image.open(BytesIO(result.data)) as raw:
            return raw.convert("RGB"), result.model, ""
    except (UnidentifiedImageError, OSError, ValueError):
        return None, "", "The image model returned an unreadable file."


def _card(db: Session, *, tenant_id: UUID, actor_id: UUID | None, creative: GrowthCreative, kit: BrandKit, platform: str, size: str, role: str, position: int, content: dict, background=None, model_id: str = "") -> tuple[GrowthAsset, dict, bytes]:
    image, layout = render_card(kit, size, background=background, **content)
    data = jpeg_bytes(image)
    provenance = "model_generated" if background is not None else "rendered"
    report = check_image(data, platform=platform, expected=SIZES[size], provenance=provenance, layout=layout)
    report["layout"] = layout
    asset = store_asset(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        data=data,
        mime="image/jpeg",
        role=role,
        creative_id=creative.id,
        position=position,
        template=f"brand-card-{size}",
        provenance=provenance,
        model_id=model_id,
        width=image.width,
        height=image.height,
        quality_state=report["state"],
        quality=report,
    )
    return asset, report, data


def _slides(kit: BrandKit, *, pillar: str, title: str, facts: list[dict], cta: str, platform: str) -> list[dict]:
    slides = [{"eyebrow": pillar, "headline": title, "body": "", "footer": kit.name, "cta": ""}]
    for fact in facts[:3]:
        statement = fact["statement"].strip()
        if fact.get("category") in {"product", "service"} and fact.get("value") and fact["value"] != statement:
            headline, body = fact["value"], statement
        else:
            first, _, rest = statement.partition(". ")
            headline, body = (first, rest) if rest and len(first) <= 110 else (statement, "")
        slides.append({"eyebrow": pillar, "headline": headline, "body": body, "footer": kit.name, "cta": ""})
    footer = "The link is in the caption." if platform == "instagram" else kit.name
    slides.append({"eyebrow": kit.name or pillar, "headline": cta or title, "body": "", "footer": footer, "cta": "Learn more" if cta else ""})
    total = len(slides)
    for index, slide in enumerate(slides):
        slide["counter"] = f"{index + 1}/{total}"
    return slides


def produce_creative(db: Session, *, tenant_id: UUID, actor_id: UUID | None, item_id: UUID, llm: LLMProvider | None = None, image_client=None, force: bool = False) -> dict:
    item = owned_item(db, tenant_id, item_id)
    if item.status in {"published", "publishing", "skipped"}:
        raise HTTPException(status_code=409, detail=f"This slot is {item.status}. No creative was produced.")
    if item.creative_id is not None and not force:
        current = db.get(GrowthCreative, item.creative_id)
        if current is not None and current.tenant_id == tenant_id and current.status in {"draft", "needs_review", "approved"}:
            return creative_view(db, tenant_id, current)
    account = db.get(GrowthAccount, item.account_id)
    strategy = strategy_for(db, item)
    if account is None or account.tenant_id != tenant_id or account.status in {"disconnected", "revoked"}:
        item.status, item.blocker = "blocked", "The account is disconnected. No creative was produced."
        raise HTTPException(status_code=409, detail=item.blocker)
    if strategy is None or strategy.status != "approved":
        item.status, item.blocker = "blocked", "The strategy for this slot is not approved. No creative was produced."
        raise HTTPException(status_code=409, detail=item.blocker)
    facts, missing = _brief_facts(db, tenant_id, item)
    if missing or not facts:
        item.status, item.blocker = "blocked", "A fact in the brief is no longer approved. Re-plan the slot."
        raise HTTPException(status_code=409, detail=item.blocker)
    brief = loads(item.brief_json, {})
    link_row = ensure_tracking_link(db, tenant_id=tenant_id, actor_id=actor_id, item=item, strategy=strategy, account=account)
    link = short_link(link_row.token) if link_row is not None else ""
    themes = [fact.statement for fact in approved_facts(db, tenant_id, ("theme",))][:8]
    profile = db.scalar(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id, BrandProfile.deleted_at.is_(None)))
    voice = loads(profile.voice_json, {}) if profile is not None else {}
    pillar_name = str((brief.get("pillar") or {}).get("name") or item.pillar_key)
    reasons: list[str] = []
    try:
        kit = brand_kit(db, tenant_id)
    except RenderUnavailable as exc:
        kit = None
        reasons.append(str(exc))
    draft = write_caption(
        db,
        tenant_id,
        platform=account.platform,
        fmt=item.format,
        brand=kit.name if kit is not None else "",
        pillar_name=pillar_name,
        facts=facts,
        cta=strategy.call_to_action,
        link=link,
        event=brief.get("event"),
        themes=themes,
        voice=voice,
        llm=llm,
    )
    support = [f"{fact.statement} {fact.evidence}" for fact in approved_facts(db, tenant_id)]
    claims = check_claims(draft.caption, support=support, review_terms=loads(strategy.review_terms_json, []))
    caption_report = check_caption(draft.caption, draft.hashtags, platform=account.platform)
    version = int(db.scalar(select(func.max(GrowthCreative.version)).where(GrowthCreative.tenant_id == tenant_id, GrowthCreative.calendar_item_id == item.id)) or 0) + 1
    for previous in db.scalars(select(GrowthCreative).where(GrowthCreative.tenant_id == tenant_id, GrowthCreative.calendar_item_id == item.id, GrowthCreative.status.in_(["draft", "needs_review"]))).all():
        previous.status = "superseded"
    creative = GrowthCreative(
        tenant_id=tenant_id,
        created_by=actor_id,
        calendar_item_id=item.id,
        account_id=account.id,
        version=version,
        format=item.format,
        title=draft.title[:300],
        caption=draft.caption,
        hashtags_json=dumps(draft.hashtags),
        alt_text=draft.alt_text,
        call_to_action=strategy.call_to_action,
        link_url=link,
        fact_ids_json=dumps(draft.fact_ids),
        claims_json=dumps(claims),
        generation=draft.generation,
        model_id=draft.model_id[:120],
        status="draft",
    )
    db.add(creative)
    db.flush()
    asset_reports: list[dict] = []
    asset_hashes: list[str] = []
    render_note = ""
    if kit is not None and item.format != "text":
        try:
            if item.format == "image":
                background, model_id, note = _background(db, tenant_id, kit, pillar_name, image_client)
                render_note = note
                asset, report, data = _card(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    creative=creative,
                    kit=kit,
                    platform=account.platform,
                    size="portrait",
                    role="image",
                    position=0,
                    content={"eyebrow": pillar_name, "headline": draft.title, "body": facts[0]["statement"] if facts[0]["statement"] != draft.title else "", "footer": kit.name, "cta": "Learn more" if strategy.call_to_action else ""},
                    background=background,
                    model_id=model_id,
                )
                asset_reports.append(report)
                asset_hashes.append(asset.sha256)
            elif item.format == "carousel":
                slide_reports = []
                for position, slide in enumerate(_slides(kit, pillar=pillar_name, title=draft.title, facts=facts, cta=strategy.call_to_action, platform=account.platform)):
                    asset, report, _data = _card(db, tenant_id=tenant_id, actor_id=actor_id, creative=creative, kit=kit, platform=account.platform, size="portrait", role="slide", position=position, content=slide)
                    slide_reports.append(report)
                    asset_hashes.append(asset.sha256)
                asset_reports.append(check_carousel(slide_reports))
                asset_reports.extend(slide_reports)
            elif item.format == "reel":
                frames: list[bytes] = []
                cover_report: dict = {}
                for position, slide in enumerate(_slides(kit, pillar=pillar_name, title=draft.title, facts=facts, cta=strategy.call_to_action, platform=account.platform)):
                    image, layout = render_card(kit, "vertical", **slide)
                    data = jpeg_bytes(image)
                    frames.append(data)
                    if position == 0:
                        cover_report = check_image(data, platform=account.platform, expected=SIZES["vertical"], provenance="rendered", layout=layout, role="cover")
                        cover_report["layout"] = layout
                        cover = store_asset(db, tenant_id=tenant_id, actor_id=actor_id, data=data, mime="image/jpeg", role="cover", creative_id=creative.id, template="brand-card-vertical", width=image.width, height=image.height, quality_state=cover_report["state"], quality=cover_report)
                        asset_hashes.append(cover.sha256)
                video = build_reel(frames, seconds=[FRAME_SECONDS] * len(frames))
                video_report = check_reel(video, max_seconds=get_settings().social_growth_reel_max_seconds)
                reel = store_asset(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    data=video,
                    mime="video/mp4",
                    role="reel",
                    creative_id=creative.id,
                    template="brand-reel-vertical",
                    width=video_report.get("width"),
                    height=video_report.get("height"),
                    duration_ms=video_report.get("duration_ms"),
                    quality_state=video_report["state"],
                    quality=video_report,
                )
                asset_hashes.append(reel.sha256)
                asset_reports.extend([cover_report, video_report])
        except (RenderUnavailable, VideoUnavailable) as exc:
            reasons.append(str(exc))
            asset_reports.append({"state": "not_configured", "checks": [{"name": "render", "ok": False, "detail": str(exc)}]})
    assets_ok = item.format == "text" or (bool(asset_reports) and all(report.get("state") == "passed" for report in asset_reports))
    if claims["unsupported"]:
        reasons.append("Unsupported claim(s): " + ", ".join(claims["unsupported"][:5]) + ".")
    if claims["sensitive"]:
        reasons.append("Sensitive term(s) need a person: " + ", ".join(claims["sensitive"][:5]) + ".")
    if not (brief.get("repetition") or {}).get("passed", True):
        reasons.append("Repetition risk: the facts were used in a recent post.")
    if caption_report["state"] != "passed":
        reasons.append("Caption checks failed: " + ", ".join(check["name"] for check in caption_report["checks"] if not check["ok"]) + ".")
    if not assets_ok and kit is not None:
        reasons.append("Asset quality checks failed.")
    if kit is not None and kit.notes:
        reasons.extend(kit.notes)
    quality_ok = caption_report["state"] == "passed" and assets_ok and kit is not None
    creative.quality_state = "passed" if quality_ok else ("not_configured" if kit is None or any(report.get("state") == "not_configured" for report in asset_reports) else "failed")
    creative.quality_json = dumps({"caption": caption_report, "assets": asset_reports, "render_note": render_note, "generation_notes": draft.notes})
    creative.review_reasons_json = dumps(reasons)
    creative.content_hash = digest(creative.caption, dumps(draft.hashtags), *sorted(asset_hashes))
    grant = active_grant(db, tenant_id, account.platform)
    if not reasons and quality_ok and strategy.auto_schedule and grant is not None:
        creative.status = "approved"
        creative.approved_at = now()
        creative.review_note = f"Approved by policy: strategy version {strategy.version} and grant {grant.name}. No unsupported claim, sensitive term, repetition risk, or failed check was found."
        item.status = "scheduled"
        item.blocker = ""
    elif reasons:
        creative.status = "needs_review"
        item.status = "needs_review"
        item.blocker = reasons[0]
    else:
        item.status = "creative_ready"
        item.blocker = "Waiting for a person to approve the creative."
    item.creative_id = creative.id
    db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="growth.creative_produce",
        entity_type="growth_creative",
        entity_id=str(creative.id),
        after={"version": version, "status": creative.status, "quality": creative.quality_state, "generation": creative.generation, "reasons": reasons[:5]},
        actor_type="human" if actor_id else "ai",
    )
    emit_event(db, tenant_id=tenant_id, event_type="social_growth.creative_ready", entity_type="growth_creative", entity_id=str(creative.id), payload={"status": creative.status, "item_id": str(item.id)})
    return creative_view(db, tenant_id, creative)


def owned_creative(db: Session, tenant_id: UUID, creative_id: UUID) -> GrowthCreative:
    row = db.scalar(select(GrowthCreative).where(GrowthCreative.tenant_id == tenant_id, GrowthCreative.id == creative_id, GrowthCreative.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail="Creative not found")
    return row


def creative_view(db: Session, tenant_id: UUID, row: GrowthCreative) -> dict:
    item = db.get(GrowthCalendarItem, row.calendar_item_id)
    account = db.get(GrowthAccount, row.account_id)
    return {
        "id": str(row.id),
        "item_id": str(row.calendar_item_id),
        "account": {"id": str(account.id), "platform": account.platform, "name": account.name or account.username, "provenance": account.provenance} if account is not None else None,
        "version": row.version,
        "format": row.format,
        "title": row.title,
        "caption": row.caption,
        "hashtags": loads(row.hashtags_json, []),
        "alt_text": row.alt_text,
        "call_to_action": row.call_to_action,
        "link_url": row.link_url,
        "fact_ids": loads(row.fact_ids_json, []),
        "claims": loads(row.claims_json, {}),
        "generation": row.generation,
        "model_id": row.model_id,
        "status": row.status,
        "review_reasons": loads(row.review_reasons_json, []),
        "quality_state": row.quality_state,
        "quality": loads(row.quality_json, {}),
        "content_hash": row.content_hash,
        "approved_at": iso(row.approved_at),
        "review_note": row.review_note,
        "planned_for": iso(item.planned_for) if item is not None else "",
        "item_status": item.status if item is not None else "",
        "brief": loads(item.brief_json, {}) if item is not None else {},
        "assets": [asset_out(asset) for asset in creative_assets(db, tenant_id, row.id)],
    }


def review_creative(db: Session, *, tenant_id: UUID, actor_id: UUID, creative_id: UUID, decision: str, note: str) -> dict:
    row = owned_creative(db, tenant_id, creative_id)
    item = db.get(GrowthCalendarItem, row.calendar_item_id)
    before = row.status
    if decision == "approve":
        if row.status not in {"draft", "needs_review"}:
            raise HTTPException(status_code=409, detail=f"Version {row.version} is {row.status}.")
        if row.quality_state != "passed":
            raise HTTPException(status_code=409, detail="Quality checks did not pass. This creative cannot be approved.")
        if loads(row.claims_json, {}).get("unsupported") and len(note.strip()) < 12:
            raise HTTPException(status_code=422, detail="Approving an unsupported claim needs a note that states the evidence.")
        row.status = "approved"
        row.approved_by = actor_id
        row.approved_at = now()
        row.review_note = note.strip()[:1000]
        if item is not None:
            item.status = "approved"
            item.blocker = ""
    elif decision == "reject":
        row.status = "rejected"
        row.review_note = note.strip()[:1000] or "Rejected in review."
        if item is not None:
            item.status = "planned"
            item.blocker = f"Creative version {row.version} was rejected: {row.review_note}"
    else:
        raise HTTPException(status_code=422, detail="Decision must be approve or reject.")
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.creative_review", entity_type="growth_creative", entity_id=str(row.id), before={"status": before}, after={"status": row.status, "note": row.review_note})
    return creative_view(db, tenant_id, row)


def revise_caption(db: Session, *, tenant_id: UUID, actor_id: UUID, creative_id: UUID, caption: str, hashtags: list[str]) -> dict:
    source = owned_creative(db, tenant_id, creative_id)
    if source.status not in {"draft", "needs_review", "approved", "rejected"}:
        raise HTTPException(status_code=409, detail=f"Version {source.version} is {source.status}.")
    item = owned_item(db, tenant_id, source.calendar_item_id)
    if item.status in {"published", "publishing"}:
        raise HTTPException(status_code=409, detail="A published post is not edited here. Plan a new post instead.")
    account = db.get(GrowthAccount, source.account_id)
    strategy = strategy_for(db, item)
    text = caption.strip()
    if not text:
        raise HTTPException(status_code=422, detail="The caption is empty.")
    tags = [tag.strip().lstrip("#") for tag in hashtags if tag.strip()]
    support = [f"{fact.statement} {fact.evidence}" for fact in approved_facts(db, tenant_id)]
    claims = check_claims(text, support=support, review_terms=loads(strategy.review_terms_json, []) if strategy is not None else [])
    caption_report = check_caption(text, tags, platform=account.platform if account is not None else "instagram")
    version = int(db.scalar(select(func.max(GrowthCreative.version)).where(GrowthCreative.tenant_id == tenant_id, GrowthCreative.calendar_item_id == item.id)) or 0) + 1
    if source.status in {"draft", "needs_review", "approved"}:
        source.status = "superseded"
    assets = creative_assets(db, tenant_id, source.id)
    row = GrowthCreative(
        tenant_id=tenant_id,
        created_by=actor_id,
        calendar_item_id=item.id,
        account_id=source.account_id,
        version=version,
        format=source.format,
        title=source.title,
        caption=text,
        hashtags_json=dumps(tags),
        alt_text=source.alt_text,
        call_to_action=source.call_to_action,
        link_url=source.link_url,
        fact_ids_json=source.fact_ids_json,
        claims_json=dumps(claims),
        generation="operator",
        status="draft",
    )
    db.add(row)
    db.flush()
    for asset in assets:
        db.add(
            GrowthAsset(
                tenant_id=tenant_id,
                created_by=actor_id,
                creative_id=row.id,
                role=asset.role,
                position=asset.position,
                mime=asset.mime,
                width=asset.width,
                height=asset.height,
                duration_ms=asset.duration_ms,
                size_bytes=asset.size_bytes,
                sha256=asset.sha256,
                object_key=asset.object_key,
                social_image_id=asset.social_image_id,
                public_url=asset.public_url,
                template=asset.template,
                provenance=asset.provenance,
                model_id=asset.model_id,
                quality_state=asset.quality_state,
                quality_json=asset.quality_json,
            )
        )
    reasons: list[str] = []
    if claims["unsupported"]:
        reasons.append("Unsupported claim(s): " + ", ".join(claims["unsupported"][:5]) + ".")
    if claims["sensitive"]:
        reasons.append("Sensitive term(s) need a person: " + ", ".join(claims["sensitive"][:5]) + ".")
    if caption_report["state"] != "passed":
        reasons.append("Caption checks failed.")
    previous = loads(source.quality_json, {})
    assets_ok = source.format == "text" or all(asset.quality_state == "passed" for asset in assets) and bool(assets)
    row.quality_state = "passed" if caption_report["state"] == "passed" and assets_ok else "failed"
    row.quality_json = dumps({**previous, "caption": caption_report})
    row.review_reasons_json = dumps(reasons)
    row.status = "needs_review" if reasons else "draft"
    row.content_hash = digest(row.caption, dumps(tags), *sorted(asset.sha256 for asset in assets))
    item.creative_id = row.id
    item.status = "needs_review" if reasons else "creative_ready"
    item.blocker = reasons[0] if reasons else "Waiting for a person to approve the edited creative."
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.creative_revise", entity_type="growth_creative", entity_id=str(row.id), before={"version": source.version}, after={"version": version, "status": row.status})
    return creative_view(db, tenant_id, row)


def schedule_item(db: Session, *, tenant_id: UUID, actor_id: UUID, item_id: UUID) -> dict:
    item = owned_item(db, tenant_id, item_id)
    creative = db.get(GrowthCreative, item.creative_id) if item.creative_id else None
    if creative is None or creative.tenant_id != tenant_id or creative.status != "approved" or creative.quality_state != "passed":
        raise HTTPException(status_code=409, detail="Only an approved creative that passed quality checks can be scheduled.")
    strategy = strategy_for(db, item)
    if strategy is None or strategy.status != "approved":
        raise HTTPException(status_code=409, detail="The strategy is not approved or is paused.")
    account = db.get(GrowthAccount, item.account_id)
    if account is None or account.status in {"disconnected", "revoked"}:
        raise HTTPException(status_code=409, detail="The account is disconnected.")
    item.status = "scheduled"
    decision, reason, _reference = publish_authorization(db, tenant_id, item, creative, account)
    approval_id = ""
    if decision == "approval":
        approval = request_publish_approval(db, tenant_id=tenant_id, actor_id=actor_id, item=item, creative=creative, account=account)
        approval_id = str(approval.id)
        item.blocker = "Waiting for publish approval in the decision inbox."
    else:
        item.blocker = ""
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.item_schedule", entity_type="growth_calendar_item", entity_id=str(item.id), after={"authorization": decision, "reason": reason, "approval_id": approval_id})
    return {"status": item.status, "authorization": decision, "detail": reason, "approval_id": approval_id, "planned_for": iso(item.planned_for)}


def review_queue(db: Session, tenant_id: UUID, *, limit: int = 50) -> list[dict]:
    rows = db.scalars(
        select(GrowthCreative)
        .where(GrowthCreative.tenant_id == tenant_id, GrowthCreative.deleted_at.is_(None), GrowthCreative.status.in_(["needs_review", "draft"]))
        .order_by(GrowthCreative.created_at.desc())
        .limit(limit)
    ).all()
    return [creative_view(db, tenant_id, row) for row in rows]
