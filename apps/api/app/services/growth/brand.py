"""Brand intelligence from the tenant's own website.

Facts keep the page, the evidence, and the time it was read. Claims wait for a
person. A page that could not be read is recorded as unreadable, not guessed.
Only approved facts reach copy.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.content import SellerProfile
from app.models.growth import BrandFact, BrandProfile, BrandSource, CompetitorBenchmark, GrowthAsset, GrowthMedia
from app.services.audit import write_audit
from app.services.discovery import bound_operating_plan
from app.services.growth.assets import asset_out, store_asset
from app.services.growth.brand_extract import (
    Finding,
    crawl_candidates,
    expand_hex,
    extract_page,
    keyphrases,
    normalize_url,
    robots_disallows,
    voice_profile,
)
from app.services.growth.common import digest, dumps, iso, loads, now
from app.services.snippet_expand import SnippetUnavailable, assert_public_url

PAGE_LIMIT = 600_000
IMAGE_LIMIT = 3_000_000
USER_AGENT = "SalesEngineBrandReader/1.0 (+brand analysis of the account owner's own site)"
CATEGORIES = (
    "company_name", "description", "product", "service", "location", "contact", "social_profile",
    "claim", "theme", "voice", "color",
)
USABLE_IN_COPY = ("company_name", "description", "product", "service", "location", "claim", "theme")


@dataclass
class FetchResult:
    url: str
    status: str
    http_status: int | None = None
    content_type: str = ""
    text: str = ""
    data: bytes = b""
    final_url: str = ""


Fetcher = Callable[[str, bool], FetchResult]


def fetch_public(url: str, binary: bool = False) -> FetchResult:
    """GET one public address. Private, local, and credentialed addresses are refused at every hop."""
    current = url
    try:
        with httpx.Client(timeout=12.0, trust_env=False, follow_redirects=False) as client:
            for _ in range(5):
                try:
                    current = assert_public_url(current)
                except SnippetUnavailable as exc:
                    status = "blocked_private" if "cannot be read" in str(exc) else "unreachable"
                    return FetchResult(url, status, final_url=current)
                accept = "image/*" if binary else "text/html,application/xhtml+xml,text/plain;q=0.8"
                response = client.get(current, headers={"User-Agent": USER_AGENT, "Accept": accept})
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location") or ""
                    if not location:
                        return FetchResult(url, "http_error", response.status_code, final_url=current)
                    current = urljoin(current, location)
                    continue
                content_type = (response.headers.get("content-type") or "").lower()
                if response.status_code >= 400:
                    return FetchResult(url, "http_error", response.status_code, content_type, final_url=current)
                body = response.content
                if len(body) > (IMAGE_LIMIT if binary else PAGE_LIMIT):
                    return FetchResult(url, "too_large", response.status_code, content_type, final_url=current)
                if binary:
                    if not content_type.startswith("image/"):
                        return FetchResult(url, "not_image", response.status_code, content_type, final_url=current)
                    return FetchResult(url, "fetched", response.status_code, content_type, data=body, final_url=current)
                if content_type and not any(token in content_type for token in ("html", "xml", "text/plain")):
                    return FetchResult(url, "not_html", response.status_code, content_type, final_url=current)
                return FetchResult(url, "fetched", response.status_code, content_type, text=response.text, final_url=current)
    except (httpx.HTTPError, ValueError):
        return FetchResult(url, "unreachable", final_url=current)
    return FetchResult(url, "unreachable", final_url=current)


def ensure_profile(db: Session, tenant_id: UUID, actor_id: UUID | None) -> BrandProfile:
    profile = db.scalar(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id, BrandProfile.deleted_at.is_(None)))
    if profile is not None:
        return profile
    seller = db.scalar(select(SellerProfile).where(SellerProfile.tenant_id == tenant_id, SellerProfile.deleted_at.is_(None)))
    plan, _message = bound_operating_plan(db, tenant_id, None)
    profile = BrandProfile(
        tenant_id=tenant_id,
        created_by=actor_id,
        website_url=normalize_url(seller.website) if seller is not None and seller.website else "",
        company_name=seller.company_name.strip() if seller is not None and seller.company_name else "",
        operating_plan_id=plan.id if plan is not None else None,
    )
    db.add(profile)
    db.flush()
    return profile


def record_source(db: Session, *, tenant_id: UUID, actor_id: UUID | None, profile: BrandProfile, kind: str, url: str, result: FetchResult | None, title: str = "", excerpt: str = "", provenance: str = "live") -> BrandSource:
    row = db.scalar(
        select(BrandSource).where(
            BrandSource.tenant_id == tenant_id,
            BrandSource.kind == kind,
            BrandSource.url == url[:1000],
            BrandSource.deleted_at.is_(None),
        )
    )
    if row is None:
        row = BrandSource(tenant_id=tenant_id, created_by=actor_id, profile_id=profile.id, kind=kind, url=url[:1000])
        db.add(row)
    row.fetched_at = now()
    row.provenance = provenance
    if result is not None:
        row.status = result.status
        row.http_status = result.http_status
        row.content_hash = digest(result.text or result.data.hex()) if result.status == "fetched" else ""
    else:
        row.status = "recorded"
    row.title = title[:300]
    row.excerpt = excerpt[:2000]
    db.flush()
    return row


def _normalized(statement: str) -> str:
    return re.sub(r"\s+", " ", statement.casefold()).strip(" .")


def remember_fact(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    profile: BrandProfile,
    finding: Finding,
    source: BrandSource | None,
    method: str = "deterministic",
    state: str = "",
) -> BrandFact | None:
    statement = finding.statement.strip()[:2000]
    if not statement or finding.category not in CATEGORIES:
        return None
    fingerprint = digest(finding.category, _normalized(statement))
    row = db.scalar(
        select(BrandFact).where(
            BrandFact.tenant_id == tenant_id,
            BrandFact.category == finding.category,
            BrandFact.fingerprint == fingerprint,
        )
    )
    observed = now()
    if row is None:
        row = BrandFact(
            tenant_id=tenant_id,
            created_by=actor_id,
            profile_id=profile.id,
            category=finding.category,
            statement=statement,
            value=(finding.value or "")[:2000],
            fingerprint=fingerprint,
            method=method,
            state=state or ("needs_review" if finding.category == "claim" else "extracted"),
            confidence=finding.confidence,
        )
        db.add(row)
    elif row.deleted_at is not None:
        row.deleted_at = None
    row.source_id = source.id if source is not None else row.source_id
    row.source_url = (source.url if source is not None else row.source_url)[:1000]
    row.evidence = (finding.evidence or statement)[:1000]
    row.observed_at = observed
    row.confidence = max(row.confidence, finding.confidence)
    db.flush()
    return row


def logo_palette(data: bytes) -> list[str]:
    try:
        with Image.open(BytesIO(data)) as raw:
            image = raw.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError):
        return []
    canvas = Image.new("RGBA", image.size, (255, 255, 255, 255))
    canvas.alpha_composite(image)
    small = canvas.convert("RGB").resize((64, 64))
    quantized = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    colors: list[str] = []
    for _count, index in sorted(quantized.getcolors() or [], reverse=True):
        red, green, blue = palette[index * 3 : index * 3 + 3]
        if max(red, green, blue) - min(red, green, blue) < 18:
            continue
        value = f"#{red:02x}{green:02x}{blue:02x}"
        if value not in colors:
            colors.append(value)
    return colors[:3]


def _image_size(data: bytes) -> tuple[int, int] | None:
    try:
        with Image.open(BytesIO(data)) as image:
            return image.size
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _store_logo(db: Session, *, tenant_id: UUID, actor_id: UUID | None, profile: BrandProfile, logo_urls: list[str], fetch: Fetcher) -> list[dict]:
    palette: list[dict] = []
    for url in logo_urls[:4]:
        result = fetch(url, True)
        if result.status != "fetched" or not result.data:
            continue
        size = _image_size(result.data)
        if size is None or min(size) < 32:
            continue
        mime = "image/png" if result.data.startswith(b"\x89PNG") else "image/jpeg" if result.data.startswith(b"\xff\xd8") else ""
        if not mime:
            with Image.open(BytesIO(result.data)) as image:
                buffer = BytesIO()
                image.convert("RGBA").save(buffer, format="PNG")
            data, mime = buffer.getvalue(), "image/png"
        else:
            data = result.data
        source = record_source(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, kind="website_asset", url=url, result=result, title="Logo")
        asset = store_asset(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            data=data,
            mime=mime,
            role="logo",
            template="website_logo",
            provenance="website",
            width=size[0],
            height=size[1],
            quality_state="passed",
            quality={"source_url": url},
        )
        profile.logo_asset_id = asset.id
        for color in logo_palette(result.data):
            palette.append({"hex": color, "source": "logo", "source_id": str(source.id), "url": url})
            remember_fact(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                profile=profile,
                finding=Finding("color", f"Colour {color} is prominent in the logo.", color, url, 75),
                source=source,
            )
        break
    return palette


def analyze_website(db: Session, *, tenant_id: UUID, actor_id: UUID | None, website_url: str = "", fetcher: Fetcher | None = None) -> dict:
    settings = get_settings()
    profile = ensure_profile(db, tenant_id, actor_id)
    if fetcher is None and (settings.social_growth_brand_fetch_mode or "live").strip().lower() != "live":
        return {"status": "blocked", "detail": "Website reading is disabled in this deployment. No page was fetched.", "brand": brand_view(db, tenant_id)}
    url = normalize_url(website_url or profile.website_url)
    if not url:
        return {"status": "blocked", "detail": "Save the company website address first. Nothing was guessed.", "brand": brand_view(db, tenant_id)}
    fetch = fetcher or fetch_public
    started = now()
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    robots_result = fetch(f"{base}/robots.txt", False)
    robots_text = robots_result.text if robots_result.status == "fetched" else ""
    record_source(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, kind="robots", url=f"{base}/robots.txt", result=robots_result, title="robots.txt")
    counts = {"fetched": 0, "failed": 0, "robots_disallowed": 0}
    if robots_text and robots_disallows(robots_text, parts.path or "/"):
        record_source(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, kind="website_page", url=url, result=FetchResult(url, "robots_disallowed"))
        profile.status = "blocked"
        profile.analysis_json = dumps({"website": url, "started_at": iso(started), "finished_at": iso(now()), "detail": "robots.txt disallows the home page."})
        return {"status": "blocked", "detail": "The site's robots.txt disallows reading the home page. Nothing was read.", "brand": brand_view(db, tenant_id)}
    home = fetch(url, False)
    if home.status != "fetched":
        record_source(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, kind="website_page", url=url, result=home)
        profile.status = "failed"
        profile.website_url = url
        profile.analysis_json = dumps({"website": url, "started_at": iso(started), "finished_at": iso(now()), "home_status": home.status})
        return {"status": "failed", "detail": f"The home page could not be read ({home.status}). No fact was recorded.", "brand": brand_view(db, tenant_id)}
    pages = [extract_page(home.final_url or url, home.text)]
    counts["fetched"] += 1
    sources = [record_source(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, kind="website_page", url=url, result=home, title=pages[0].title, excerpt=pages[0].text)]
    for candidate in crawl_candidates(pages[0], max(0, settings.social_growth_max_pages - 1)):
        path = urlsplit(candidate).path or "/"
        if robots_text and robots_disallows(robots_text, path):
            counts["robots_disallowed"] += 1
            record_source(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, kind="website_page", url=candidate, result=FetchResult(candidate, "robots_disallowed"))
            continue
        result = fetch(candidate, False)
        if result.status != "fetched":
            counts["failed"] += 1
            record_source(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, kind="website_page", url=candidate, result=result)
            continue
        page = extract_page(result.final_url or candidate, result.text)
        pages.append(page)
        counts["fetched"] += 1
        sources.append(record_source(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, kind="website_page", url=candidate, result=result, title=page.title, excerpt=page.text))
    by_category: dict[str, int] = {}
    for page, source in zip(pages, sources, strict=True):
        for finding in page.findings:
            if remember_fact(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, finding=finding, source=source) is not None:
                by_category[finding.category] = by_category.get(finding.category, 0) + 1
    texts = [page.text for page in pages]
    for phrase, count in keyphrases(texts):
        remember_fact(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            profile=profile,
            finding=Finding("theme", phrase, phrase, f"Appears {count} times across {len(pages)} page(s).", 60),
            source=sources[0],
        )
        by_category["theme"] = by_category.get("theme", 0) + 1
    voice = voice_profile(texts)
    voice["source_ids"] = [str(source.id) for source in sources]
    voice["measured_at"] = iso(now())
    profile.voice_json = dumps(voice)
    palette = [
        {"hex": expand_hex(finding.value), "source": "page", "source_id": str(source.id), "url": source.url}
        for page, source in zip(pages, sources, strict=True)
        for finding in page.findings
        if finding.category == "color" and finding.value
    ]
    logo_urls = [url for page in pages for url in page.logo_urls]
    palette = _store_logo(db, tenant_id=tenant_id, actor_id=actor_id, profile=profile, logo_urls=list(dict.fromkeys(logo_urls)), fetch=fetch) + palette
    unique: list[dict] = []
    for entry in palette:
        if all(entry["hex"] != kept["hex"] for kept in unique):
            unique.append(entry)
    profile.palette_json = dumps(unique[:6])
    names = db.scalars(
        select(BrandFact)
        .where(BrandFact.tenant_id == tenant_id, BrandFact.category == "company_name", BrandFact.deleted_at.is_(None))
        .order_by(BrandFact.confidence.desc())
    ).all()
    if names:
        profile.company_name = names[0].statement[:200]
    profile.website_url = url
    profile.last_analysis_at = now()
    profile.status = "analyzed" if counts["failed"] == 0 else "partial"
    profile.analysis_json = dumps(
        {
            "website": url,
            "started_at": iso(started),
            "finished_at": iso(now()),
            "pages_fetched": counts["fetched"],
            "pages_failed": counts["failed"],
            "pages_disallowed": counts["robots_disallowed"],
            "facts_by_category": by_category,
            "method": "deterministic extraction from fetched HTML; no model",
        }
    )
    db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="growth.brand_analyze",
        entity_type="brand_profile",
        entity_id=str(profile.id),
        after={"website": url, **counts},
        actor_type="human" if actor_id else "ai",
    )
    detail = f"Read {counts['fetched']} page(s). {counts['failed']} could not be read. Facts wait for review before they reach copy."
    return {"status": profile.status, "detail": detail, "brand": brand_view(db, tenant_id)}


def fact_out(row: BrandFact) -> dict:
    return {
        "id": str(row.id),
        "category": row.category,
        "statement": row.statement,
        "value": row.value,
        "source_url": row.source_url,
        "source_id": str(row.source_id or ""),
        "evidence": row.evidence,
        "observed_at": iso(row.observed_at),
        "method": row.method,
        "state": row.state,
        "confidence": row.confidence,
        "reviewed_at": iso(row.reviewed_at),
        "review_note": row.review_note,
    }


def brand_view(db: Session, tenant_id: UUID) -> dict:
    profile = db.scalar(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id, BrandProfile.deleted_at.is_(None)))
    if profile is None:
        return {"status": "not_started", "profile": None, "facts": [], "sources": [], "competitors": [], "history": [], "counts": {}}
    facts = db.scalars(
        select(BrandFact)
        .where(BrandFact.tenant_id == tenant_id, BrandFact.deleted_at.is_(None))
        .order_by(BrandFact.category.asc(), BrandFact.confidence.desc(), BrandFact.created_at.asc())
    ).all()
    sources = db.scalars(
        select(BrandSource)
        .where(BrandSource.tenant_id == tenant_id, BrandSource.deleted_at.is_(None))
        .order_by(BrandSource.fetched_at.desc())
        .limit(60)
    ).all()
    competitors = db.scalars(
        select(CompetitorBenchmark).where(CompetitorBenchmark.tenant_id == tenant_id, CompetitorBenchmark.deleted_at.is_(None))
    ).all()
    history = db.execute(
        select(GrowthMedia.account_id, GrowthMedia.origin, func.count(), func.min(GrowthMedia.posted_at), func.max(GrowthMedia.posted_at))
        .where(GrowthMedia.tenant_id == tenant_id, GrowthMedia.deleted_at.is_(None))
        .group_by(GrowthMedia.account_id, GrowthMedia.origin)
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for row in facts:
        bucket = counts.setdefault(row.category, {})
        bucket[row.state] = bucket.get(row.state, 0) + 1
    logo = db.get(GrowthAsset, profile.logo_asset_id) if profile.logo_asset_id else None
    return {
        "status": profile.status,
        "profile": {
            "id": str(profile.id),
            "website_url": profile.website_url,
            "company_name": profile.company_name,
            "last_analysis_at": iso(profile.last_analysis_at),
            "analysis": loads(profile.analysis_json, {}),
            "palette": loads(profile.palette_json, []),
            "voice": loads(profile.voice_json, {}),
            "operating_plan_id": str(profile.operating_plan_id or ""),
            "logo": asset_out(logo) if logo is not None and logo.tenant_id == tenant_id else None,
            "competitor_usernames": loads(profile.competitor_usernames, []),
        },
        "facts": [fact_out(row) for row in facts],
        "counts": counts,
        "sources": [
            {
                "id": str(row.id),
                "kind": row.kind,
                "url": row.url,
                "title": row.title,
                "status": row.status,
                "http_status": row.http_status,
                "fetched_at": iso(row.fetched_at),
                "provenance": row.provenance,
            }
            for row in sources
        ],
        "competitors": [competitor_out(row) for row in competitors],
        "history": [
            {"account_id": str(account_id), "origin": origin, "posts": int(total), "oldest": iso(oldest), "newest": iso(newest)}
            for account_id, origin, total, oldest, newest in history
        ],
    }


def competitor_out(row: CompetitorBenchmark) -> dict:
    return {
        "id": str(row.id),
        "platform": row.platform,
        "username": row.username,
        "status": row.status,
        "followers_count": row.followers_count,
        "media_count": row.media_count,
        "sample_size": row.sample_size,
        "posts_per_week": str(row.posts_per_week) if row.posts_per_week is not None else None,
        "avg_likes": str(row.avg_likes) if row.avg_likes is not None else None,
        "avg_comments": str(row.avg_comments) if row.avg_comments is not None else None,
        "retrieved_at": iso(row.retrieved_at),
        "source": row.source,
        "provenance": row.provenance,
        "error": row.error,
    }


def review_facts(db: Session, *, tenant_id: UUID, actor_id: UUID, fact_ids: list[UUID], decision: str, note: str = "") -> dict:
    target = {"approve": "approved", "reject": "rejected", "reopen": "needs_review"}.get(decision)
    if target is None:
        return {"updated": 0, "detail": "Decision must be approve, reject, or reopen."}
    updated = 0
    for fact_id in fact_ids:
        row = db.scalar(select(BrandFact).where(BrandFact.tenant_id == tenant_id, BrandFact.id == fact_id, BrandFact.deleted_at.is_(None)))
        if row is None:
            continue
        before = row.state
        if before == target:
            continue
        row.state = target
        row.reviewed_by = actor_id
        row.reviewed_at = now()
        row.review_note = note.strip()[:1000]
        write_audit(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="growth.fact_review",
            entity_type="brand_fact",
            entity_id=str(row.id),
            before={"state": before},
            after={"state": target, "category": row.category, "note": row.review_note},
        )
        updated += 1
    db.flush()
    return {"updated": updated, "detail": f"{updated} fact(s) are now {target}."}


def add_operator_fact(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    category: str,
    statement: str,
    source_url: str,
    evidence: str,
    approve: bool,
) -> dict:
    if category not in CATEGORIES:
        return {"status": "blocked", "detail": "Unknown fact category."}
    if category == "claim" and not (source_url.strip() or evidence.strip()):
        return {"status": "blocked", "detail": "A claim needs a source address or written evidence. Nothing was saved."}
    profile = ensure_profile(db, tenant_id, actor_id)
    source = record_source(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        profile=profile,
        kind="operator",
        url=source_url.strip() or f"operator:{digest(statement)[:16]}",
        result=None,
        title="Operator-recorded fact",
        excerpt=evidence,
        provenance="operator",
    )
    row = remember_fact(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        profile=profile,
        finding=Finding(category, statement, statement, evidence or statement, 100),
        source=source,
        method="operator",
        state="approved" if approve else "needs_review",
    )
    if row is None:
        return {"status": "blocked", "detail": "The statement was empty."}
    if approve:
        row.reviewed_by = actor_id
        row.reviewed_at = now()
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.fact_add", entity_type="brand_fact", entity_id=str(row.id), after=fact_out(row))
    return {"status": "saved", "fact": fact_out(row)}


def approved_facts(db: Session, tenant_id: UUID, categories: tuple[str, ...] = USABLE_IN_COPY) -> list[BrandFact]:
    return list(
        db.scalars(
            select(BrandFact)
            .where(
                BrandFact.tenant_id == tenant_id,
                BrandFact.deleted_at.is_(None),
                BrandFact.state == "approved",
                BrandFact.category.in_(categories),
            )
            .order_by(BrandFact.category.asc(), BrandFact.created_at.asc())
        ).all()
    )
