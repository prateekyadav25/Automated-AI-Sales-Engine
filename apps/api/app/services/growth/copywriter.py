"""Captions from approved facts only.

The model path receives the approved facts, the pillar, the call to action,
the tracking link, and measured voice traits, and must return JSON. A mock or
unconfigured model, a failed call, or unusable output falls back to a labeled
deterministic caption assembled from the same facts. The claim checker runs on
both.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import LLMProvider, MockLLMProvider, NotConfiguredLLMProvider, get_llm_provider
from app.models.ai import ModelUsage, Prompt

PROMPT_KEY = "social_growth_caption"
PROMPT_VERSION = "1"
CAPTION_SYSTEM = (
    "You write one organic social media caption for the brand described in the input. "
    "Use only the facts provided. Do not add numbers, prices, customers, awards, rankings, comparisons, "
    "guarantees, or results that are not written in the facts. Keep the call to action and the link exactly as given. "
    "Match the measured voice traits. Return JSON only: "
    '{"caption": "...", "hashtags": ["..."], "fact_ids": ["..."]}'
)
TAG_LIMITS = {"instagram": 5, "facebook": 3}


@dataclass
class CaptionDraft:
    caption: str
    hashtags: list[str]
    title: str
    alt_text: str
    fact_ids: list[str]
    generation: str
    model_id: str = ""
    notes: list[str] = field(default_factory=list)


def prompt_template(db: Session, tenant_id: UUID) -> str:
    row = db.scalar(
        select(Prompt).where(Prompt.tenant_id == tenant_id, Prompt.prompt_key == PROMPT_KEY, Prompt.status == "approved", Prompt.deleted_at.is_(None))
    )
    return row.template if row is not None and row.template.strip() else CAPTION_SYSTEM


def hashtag(text: str) -> str:
    raw = text.strip().lstrip("#")
    if re.fullmatch(r"[A-Za-z0-9_]{2,40}", raw):
        return raw
    words = re.findall(r"[A-Za-z0-9]+", raw)
    tag = "".join(word[:1].upper() + word[1:] for word in words)
    return tag[:40] if len(tag) >= 2 else ""


def _first_sentence(text: str, limit: int) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0].rstrip(".")
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def deterministic_caption(*, platform: str, brand: str, pillar_name: str, facts: list[dict], cta: str, link: str, event: dict | None, themes: list[str]) -> CaptionDraft:
    lead = facts[0]
    lines: list[str] = []
    if event:
        lines.append(str(event.get("title") or "").strip())
    lines.append(lead["statement"].strip())
    for extra in facts[1:2]:
        if extra["statement"].strip() and extra["statement"].strip() != lead["statement"].strip():
            lines.append(extra["statement"].strip())
    action = cta.strip().rstrip(".") + "." if cta.strip() else ""
    if link:
        action = f"{action} {link}".strip() if platform == "facebook" else f"{action} Link: {link}".strip()
    if action:
        lines.append(action)
    tags = [tag for tag in (hashtag(theme) for theme in themes) if tag][: TAG_LIMITS.get(platform, 3)]
    title_source = lead.get("value") if lead.get("category") in {"product", "service"} and lead.get("value") else lead["statement"]
    title = _first_sentence(str(title_source), 70)
    alt = f"{brand} graphic with the headline: {title}." if brand else f"Graphic with the headline: {title}."
    return CaptionDraft(
        caption="\n\n".join(line for line in lines if line),
        hashtags=list(dict.fromkeys(tags)),
        title=title,
        alt_text=alt[:300],
        fact_ids=[str(item["id"]) for item in facts[:2]],
        generation="deterministic",
        notes=[f"Pillar: {pillar_name}." if pillar_name else "Deterministic caption from approved facts."],
    )


def _parse(text: str) -> dict | None:
    cleaned = text.strip()
    fenced = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if fenced is None:
        return None
    try:
        value = json.loads(fenced.group(0))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def write_caption(
    db: Session,
    tenant_id: UUID,
    *,
    platform: str,
    fmt: str,
    brand: str,
    pillar_name: str,
    facts: list[dict],
    cta: str,
    link: str,
    event: dict | None,
    themes: list[str],
    voice: dict,
    llm: LLMProvider | None = None,
) -> CaptionDraft:
    base = deterministic_caption(platform=platform, brand=brand, pillar_name=pillar_name, facts=facts, cta=cta, link=link, event=event, themes=themes)
    provider = llm or get_llm_provider(db, tenant_id)
    if isinstance(provider, (MockLLMProvider, NotConfiguredLLMProvider)):
        base.notes.append("The model is mock or not configured, so the caption is the deterministic version.")
        return base
    payload = {
        "platform": platform,
        "format": fmt,
        "brand": brand,
        "pillar": pillar_name,
        "facts": [{"id": str(item["id"]), "statement": item["statement"]} for item in facts],
        "call_to_action": cta,
        "link": link,
        "event": event,
        "voice": {key: voice.get(key) for key in ("average_sentence_words", "second_person_share", "first_person_plural_share", "exclamation_share")},
        "max_characters": 1800 if platform == "instagram" else 1500,
        "max_hashtags": TAG_LIMITS.get(platform, 3),
        "allowed_hashtag_sources": themes,
    }
    try:
        result = provider.complete(json.dumps(payload), system=prompt_template(db, tenant_id))
    except Exception as exc:  # noqa: BLE001 - any provider failure falls back to the labeled deterministic caption
        base.notes.append(f"The model call failed ({exc.__class__.__name__}). The deterministic caption was used.")
        return base
    db.add(
        ModelUsage(
            tenant_id=tenant_id,
            provider=result.provider,
            model=result.model[:80],
            agent="social_growth_copywriter",
            prompt_version=PROMPT_VERSION,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            estimated_cost=result.estimated_cost,
            is_mock=result.is_mock,
        )
    )
    parsed = _parse(result.text or "")
    caption = str((parsed or {}).get("caption") or "").strip()
    if not caption:
        base.notes.append("The model returned no usable caption. The deterministic caption was used.")
        return base
    known = {str(item["id"]) for item in facts}
    fact_ids = [str(item) for item in (parsed or {}).get("fact_ids") or [] if str(item) in known] or base.fact_ids
    if link and link not in caption:
        caption = f"{caption}\n\n{cta.strip()} {link}".strip()
    tags = [tag for tag in (hashtag(str(item)) for item in (parsed or {}).get("hashtags") or []) if tag][: TAG_LIMITS.get(platform, 3)]
    return CaptionDraft(
        caption=caption[:2100],
        hashtags=list(dict.fromkeys(tags)),
        title=base.title,
        alt_text=base.alt_text,
        fact_ids=fact_ids,
        generation="model",
        model_id=result.model,
        notes=["Model caption. Claims are checked against approved facts before review."],
    )
