"""Reviewable content proposals for one selected operating plan.

Proposals stay separate from authorized creative versions. Copy uses the
frozen product context. A topic is not described as trending.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.operating_plan import CreativeVersion
from app.models.organic import ContentProposal
from app.providers.social import provider_can_fetch
from app.services.audit import write_audit
from app.services.discovery import bound_operating_plan
from app.services.product_context import CONTEXT_VERSION, build_product_context
from app.services.social_media import image_kind, store_social_image

SUPPORTED_CHANNELS = {"linkedin", "facebook", "instagram"}
CHANNEL_FORMAT = {"linkedin": "text", "facebook": "text", "instagram": "image"}
IMAGE_RULES = {
    "linkedin": {"min_width": 552, "min_height": 276, "recommended": "1200×627"},
    "instagram": {"min_width": 320, "min_height": 320, "recommended": "1080×1080"},
    "facebook": {"min_width": 200, "min_height": 200, "recommended": "1200×630"},
}
_PNG = b"\x89PNG\r\n\x1a\n"


def propose_calendar(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    plan_id: UUID | None,
    objective: str,
    audience: str,
    channels: list[str],
    start_on: str,
    end_on: str,
    cadence_days: int,
    themes: list[str],
    call_to_action: str,
) -> dict:
    plan, message = bound_operating_plan(db, tenant_id, plan_id)
    if message.startswith("More than one"):
        return {"detail": "More than one operating plan is open. Choose the plan before preparing content.", "status": "blocked", "next_action": "choose_operating_plan", "proposals": []}
    if message:
        return {"detail": message, "status": "blocked", "next_action": "choose_operating_plan", "proposals": []}
    if plan is None:
        return {"detail": "Start an operating plan before preparing content.", "status": "blocked", "next_action": "start_operating_plan", "proposals": []}
    selected = _channels(channels)
    if not selected:
        return {"detail": "Choose a supported channel. LinkedIn, Facebook, and Instagram are the channels this calendar can prepare.", "status": "blocked", "next_action": "choose_channel", "proposals": []}
    chosen_themes = [item.strip() for item in themes if item.strip()]
    if not chosen_themes:
        return {"detail": "Add at least one content theme. No calendar was invented.", "status": "blocked", "next_action": "add_theme", "proposals": []}
    start, end = _dates(start_on, end_on)
    if start is None or end is None or end < start:
        return {"detail": "The date range is missing or ends before it starts.", "status": "blocked", "next_action": "choose_dates", "proposals": []}
    step = cadence_days if cadence_days > 0 else 0
    if step <= 0:
        return {"detail": "The posting cadence must be at least one day.", "status": "blocked", "next_action": "choose_cadence", "proposals": []}
    context = build_product_context(db, tenant_id, plan=plan)
    if "customer_facing_name" in context.missing or "description" in context.missing:
        return {"detail": "The selected product has no customer-facing name or description. Content was not invented.", "status": "blocked", "next_action": "save_product_knowledge", "proposals": []}
    brief = {
        "objective": objective.strip(),
        "audience": audience.strip() or context.audience,
        "channels": selected,
        "start_on": start.date().isoformat(),
        "end_on": end.date().isoformat(),
        "cadence_days": step,
        "themes": chosen_themes,
        "call_to_action": call_to_action.strip(),
    }
    plan.content_brief_json = json.dumps(brief)
    people = brief["audience"] or "the saved audience"
    action = brief["call_to_action"] or "Tell us what you want to improve."
    created = 0
    for channel in selected:
        for theme in chosen_themes:
            for when in _slots(start, end, step):
                if _store_proposal(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    plan=plan,
                    channel=channel,
                    theme=theme,
                    when=when,
                    context=context,
                    people=people,
                    objective=brief["objective"],
                    action=action,
                ):
                    created += 1
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="operating_plan.content_calendar",
        entity_type="operating_plan",
        entity_id=str(plan.id),
        after={"created": created, "channels": selected},
    )
    return {
        "detail": f"{created} content proposal{'s' if created != 1 else ''} {'are' if created != 1 else 'is'} waiting for review. Nothing was scheduled.",
        "status": plan.status,
        "next_action": "review_content_proposals",
        "proposals": list_proposals(db, tenant_id, plan.id),
        "customer_facing_name": context.customer_facing_name,
        "offer_label": context.offer_label(),
    }


def list_proposals(db: Session, tenant_id: UUID, plan_id: UUID) -> list[dict]:
    rows = db.scalars(
        select(ContentProposal)
        .where(
            ContentProposal.tenant_id == tenant_id,
            ContentProposal.plan_id == plan_id,
            ContentProposal.deleted_at.is_(None),
        )
        .order_by(ContentProposal.proposed_for.asc(), ContentProposal.topic.asc())
    ).all()
    return [_proposal_out(row) for row in rows]


def attach_local_preview(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    proposal_id: UUID,
    data: bytes,
) -> dict:
    row = _proposal(db, tenant_id, proposal_id)
    if row is None:
        return {"detail": "That content proposal was not found.", "asset_state": "missing"}
    if row.format == "video":
        row.asset_state = "unsupported"
        row.asset_note = "Video generation is not available. The brief is text and was not presented as a video."
        row.public_media_ready = False
        return _proposal_out(row)
    if row.format != "image":
        row.asset_note = "This format does not require an image. The copy is the preview."
        return _proposal_out(row)
    kind = image_kind(data)
    size = _dimensions(data)
    rule = IMAGE_RULES.get(row.channel, IMAGE_RULES["linkedin"])
    if kind is None or size is None:
        row.asset_state = "invalid"
        row.asset_note = "The file was not a readable JPEG or PNG. No preview was stored."
        row.public_media_ready = False
        return _proposal_out(row)
    width, height = size
    if width < rule["min_width"] or height < rule["min_height"]:
        row.asset_state = "invalid"
        row.asset_note = (
            f"The image is {width}×{height}. {row.channel} needs at least "
            f"{rule['min_width']}×{rule['min_height']}. Recommended {rule['recommended']}. No preview was stored."
        )
        row.public_media_ready = False
        return _proposal_out(row)
    url = store_social_image(db, tenant_id=tenant_id, actor_id=actor_id, data=data)
    ready = provider_can_fetch(url)
    row.asset_url = url
    row.asset_state = "local_preview"
    row.public_media_ready = ready
    row.asset_note = (
        f"Local {kind} preview, {width}×{height}. Recommended {rule['recommended']}. "
        "A public media URL is a separate requirement before a live post."
    )
    return _proposal_out(row)


def promote_proposal(db: Session, *, tenant_id: UUID, actor_id: UUID, proposal_id: UUID) -> dict:
    row = _proposal(db, tenant_id, proposal_id)
    if row is None:
        return {"detail": "That content proposal was not found.", "status": "blocked"}
    if row.status == "promoted" and row.creative_version_id is not None:
        return {"detail": "This proposal already has a draft version. A second version was not created.", "version_id": str(row.creative_version_id), "status": "draft"}
    if row.format == "video" or row.asset_state == "unsupported":
        row.asset_state = "unsupported"
        row.asset_note = "Video generation is not available. The brief is text and was not presented as a video."
        return {"detail": row.asset_note, "status": "unsupported", "version_id": ""}
    if row.format == "image" and row.asset_state != "local_preview":
        return {
            "detail": "The image preview is missing or invalid. A text brief was not treated as an image.",
            "status": row.asset_state or "missing",
            "version_id": "",
        }
    number = int(
        db.scalar(
            select(func.max(CreativeVersion.version_number)).where(
                CreativeVersion.tenant_id == tenant_id,
                CreativeVersion.plan_id == row.plan_id,
                CreativeVersion.deleted_at.is_(None),
            )
        )
        or 0
    ) + 1
    image = row.asset_url if row.format == "image" else ""
    version = CreativeVersion(
        tenant_id=tenant_id,
        created_by=actor_id,
        plan_id=row.plan_id,
        channel=row.channel,
        version_number=number,
        headline=row.topic[:300],
        body=row.body,
        image_url=image,
        content_hash=_hash(row.topic, row.body, image),
        status="draft",
        publication_token=uuid4().hex,
        context_json=row.context_json,
    )
    db.add(version)
    db.flush()
    row.status = "promoted"
    row.creative_version_id = version.id
    return {"detail": f"Proposal became draft version {number}. It is not authorized or scheduled.", "version_id": str(version.id), "status": "draft", "version": number}


def _store_proposal(db, *, tenant_id, actor_id, plan, channel, theme, when, context, people, objective, action) -> bool:
    existing = db.scalar(
        select(ContentProposal).where(
            ContentProposal.tenant_id == tenant_id,
            ContentProposal.plan_id == plan.id,
            ContentProposal.channel == channel,
            ContentProposal.topic == theme[:200],
            ContentProposal.proposed_for == when,
            ContentProposal.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return False
    fmt = CHANNEL_FORMAT[channel]
    include_price = "price" in objective.casefold() or "price" in theme.casefold()
    parts = [context.customer_facing_name, context.description, theme]
    if include_price and context.price_line():
        parts.append(context.price_line())
    parts.append(action)
    missing = ["No stored research supports a trend or audience claim beyond the saved product facts."]
    if "supporting_facts" in context.missing:
        missing.append("Supporting company facts are missing.")
    if "benefits" in context.missing:
        missing.append("No approved benefit list is stored.")
    asset_state = "not_required" if fmt == "text" else "missing"
    asset_note = "The copy is the preview." if fmt == "text" else "An image is required. A text brief is not an image."
    if channel == "instagram":
        asset_note = "Instagram needs an image. A text brief is not an image. Live publishing also needs a public media URL."
    row = ContentProposal(
        tenant_id=tenant_id,
        created_by=actor_id,
        plan_id=plan.id,
        channel=channel,
        format=fmt,
        topic=theme[:200],
        audience_relevance=f"For {people}. Objective: {objective or 'not supplied'}.",
        body="\n\n".join(part for part in parts if part),
        call_to_action=action,
        brief=f"{channel} {fmt} post about {theme}. Use only the stored product facts.",
        asset_state=asset_state,
        asset_note=asset_note,
        proposed_for=when,
        sources_json=json.dumps(
            [
                {"kind": "product_context", "ref": CONTEXT_VERSION},
                {"kind": "operator_theme", "ref": theme},
                {"kind": "catalogue", "ref": context.sku},
            ]
        ),
        missing_research=" ".join(missing),
        status="proposed",
        context_json=json.dumps(context.as_dict()),
        context_version=CONTEXT_VERSION,
        public_media_ready=False,
    )
    if "trending" in row.body.casefold() or "viral" in row.body.casefold():
        row.body = row.body.replace("trending", "").replace("Trending", "")
    db.add(row)
    db.flush()
    return True


def _proposal(db: Session, tenant_id: UUID, proposal_id: UUID | str) -> ContentProposal | None:
    try:
        parsed = proposal_id if isinstance(proposal_id, UUID) else UUID(str(proposal_id))
    except ValueError:
        return None
    return db.scalar(
        select(ContentProposal).where(
            ContentProposal.tenant_id == tenant_id,
            ContentProposal.id == parsed,
            ContentProposal.deleted_at.is_(None),
        )
    )


def _proposal_out(row: ContentProposal) -> dict:
    try:
        sources = json.loads(row.sources_json or "[]")
    except json.JSONDecodeError:
        sources = []
    return {
        "id": str(row.id),
        "channel": row.channel,
        "format": row.format,
        "topic": row.topic,
        "audience_relevance": row.audience_relevance,
        "body": row.body,
        "call_to_action": row.call_to_action,
        "brief": row.brief,
        "asset_state": row.asset_state,
        "asset_url": row.asset_url,
        "asset_note": row.asset_note,
        "proposed_for": row.proposed_for.isoformat(),
        "sources": sources if isinstance(sources, list) else [],
        "missing_research": row.missing_research,
        "status": row.status,
        "creative_version_id": str(row.creative_version_id or ""),
        "public_media_ready": bool(row.public_media_ready),
        "context_version": row.context_version,
    }


def _channels(values: list[str]) -> list[str]:
    chosen: list[str] = []
    for value in values:
        name = value.strip().lower()
        if name in SUPPORTED_CHANNELS and name not in chosen:
            chosen.append(name)
    return chosen


def _dates(start_on: str, end_on: str) -> tuple[datetime | None, datetime | None]:
    try:
        start = datetime.fromisoformat(start_on).replace(tzinfo=UTC, hour=9, minute=0, second=0, microsecond=0)
        end = datetime.fromisoformat(end_on).replace(tzinfo=UTC, hour=9, minute=0, second=0, microsecond=0)
    except ValueError:
        return None, None
    return start, end


def _slots(start: datetime, end: datetime, step: int) -> list[datetime]:
    slots: list[datetime] = []
    cursor = start
    while cursor <= end and len(slots) < 12:
        slots.append(cursor)
        cursor = cursor + timedelta(days=step)
    return slots


def _hash(headline: str, body: str, image_url: str) -> str:
    material = f"{headline}|{body}|{image_url}".strip()
    return hashlib.sha256(material.encode()).hexdigest()


def _dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(_PNG) and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data.startswith(b"\xff\xd8\xff"):
        return _jpeg_size(data)
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    index = 2
    while index + 8 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in {0xC0, 0xC1, 0xC2}:
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return int(width), int(height)
        if index + 4 > len(data):
            return None
        length = struct.unpack(">H", data[index + 2 : index + 4])[0]
        index += 2 + length
    return None


def solid_png(width: int, height: int, rgb: tuple[int, int, int] = (18, 72, 120)) -> bytes:
    """A valid solid PNG for local preview fixtures. It is not a purchased render."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return _PNG + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
