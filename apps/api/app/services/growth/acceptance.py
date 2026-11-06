"""Live acceptance steps for Social Growth.

A step is verified only when this workspace has both a stored authorization
and evidence recorded from a provider client this process opened. A fixture
account, a scripted test client, and a row marked live or mock do not count.
Authorizing a step writes the decision and does not call Meta or Google.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.growth import (
    BrandProfile,
    GrowthAcceptanceGate,
    GrowthAccount,
    GrowthMedia,
    GrowthMetricObservation,
    GrowthPublication,
    GrowthTrafficObservation,
)
from app.services.audit import write_audit
from app.services.growth.common import iso, loads, now
from app.services.growth.video import VideoUnavailable, tools

STEPS: tuple[tuple[str, str], ...] = (
    ("token_verification", "Token verification"),
    ("history_import", "Historical post import"),
    ("meta_insights", "Meta insights retrieval"),
    ("ga4", "GA4 insights retrieval"),
    ("facebook_post", "Publish one Facebook post"),
    ("instagram_image", "Publish one Instagram image"),
    ("instagram_reel", "Publish one Instagram Reel"),
)
KNOWN = {key for key, _title in STEPS}
PROVIDER = "provider"


def acceptance_step(platform: str, creative_format: str) -> str:
    """Map one publish attempt to its checklist step. An unlisted format has no step."""
    if platform == "facebook":
        return "facebook_post"
    if platform == "instagram" and creative_format == "reel":
        return "instagram_reel"
    if platform == "instagram" and creative_format == "image":
        return "instagram_image"
    return ""


def require_authorized(db: Session, tenant_id: UUID, step_key: str) -> str:
    """Return a refusal when this workspace has not authorized the step. An empty string allows it."""
    if step_key not in KNOWN:
        return "This action is not in the acceptance checklist. Nothing was requested."
    row = _gate(db, tenant_id, step_key)
    if row is None:
        return "Awaiting authorization. Nothing was requested from the provider."
    return ""


def authorize(db: Session, *, tenant_id: UUID, actor_id: UUID, step_key: str, note: str) -> dict:
    """Record approval for one step. This does not open a provider client or publish."""
    if step_key not in KNOWN:
        raise HTTPException(status_code=404, detail="Unknown acceptance step.")
    cleaned = note.strip()
    if len(cleaned) < 12:
        raise HTTPException(status_code=422, detail="Name the account and the exact action in the authorization note.")
    row = _gate(db, tenant_id, step_key)
    if row is None:
        row = GrowthAcceptanceGate(tenant_id=tenant_id, created_by=actor_id, step_key=step_key)
        db.add(row)
    row.authorized_at = now()
    row.note = cleaned[:2000]
    row.updated_by = actor_id
    db.flush()
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="growth.acceptance_authorize",
        entity_type="growth_acceptance_gate",
        entity_id=str(row.id),
        after={"step_key": step_key},
    )
    return _view(db, tenant_id, step_key, _title(step_key), row)


def overview(db: Session, tenant_id: UUID) -> list[dict]:
    gates = {row.step_key: row for row in db.scalars(select(GrowthAcceptanceGate).where(GrowthAcceptanceGate.tenant_id == tenant_id, GrowthAcceptanceGate.deleted_at.is_(None))).all()}
    return [_view(db, tenant_id, key, title, gates.get(key)) for key, title in STEPS]


def _title(step_key: str) -> str:
    for key, title in STEPS:
        if key == step_key:
            return title
    return step_key


def _gate(db: Session, tenant_id: UUID, step_key: str) -> GrowthAcceptanceGate | None:
    return db.scalar(
        select(GrowthAcceptanceGate).where(
            GrowthAcceptanceGate.tenant_id == tenant_id,
            GrowthAcceptanceGate.step_key == step_key,
            GrowthAcceptanceGate.deleted_at.is_(None),
        )
    )


def _view(db: Session, tenant_id: UUID, step_key: str, title: str, gate: GrowthAcceptanceGate | None) -> dict:
    status, reason = _status(db, tenant_id, step_key, gate is not None)
    return {
        "step_key": step_key,
        "title": title,
        "status": status,
        "reason": reason,
        "authorized_at": iso(gate.authorized_at) if gate is not None and gate.authorized_at is not None else "",
        "note": gate.note if gate is not None else "",
    }


def _status(db: Session, tenant_id: UUID, step_key: str, authorized: bool) -> tuple[str, str]:
    unsupported = _unsupported(step_key)
    if unsupported:
        return "not_supported", unsupported
    evidence = _provider_evidence(db, tenant_id, step_key)
    if evidence and authorized:
        return "verified_live", evidence
    if evidence:
        return "failed", "Provider evidence exists without an authorization record."
    failure = _failure(db, tenant_id, step_key)
    if failure and authorized:
        return "failed", failure
    blocked = _config_block(db, tenant_id, step_key)
    if blocked:
        return "blocked", blocked
    if not authorized:
        return "not_started", "This step has not been authorized. No provider request will run."
    return "awaiting_authorization", "Authorized. A real provider result has not been stored. A fixture or mock result does not count."


def _unsupported(step_key: str) -> str:
    if step_key != "instagram_reel":
        return ""
    try:
        tools()
    except VideoUnavailable as exc:
        return str(exc)
    return ""


def _config_block(db: Session, tenant_id: UUID, step_key: str) -> str:
    settings = get_settings()
    accounts = _live_accounts(db, tenant_id)
    if step_key == "token_verification":
        if not settings.meta_app_id or not settings.meta_app_secret:
            return "META_APP_ID and META_APP_SECRET are not configured."
        return _meta_read_block(settings.social_growth_insights_mode, accounts)
    if step_key in {"history_import", "meta_insights"}:
        return _meta_read_block(settings.social_growth_insights_mode, accounts)
    if step_key == "ga4":
        if (settings.ga4_mode or "disabled").strip().lower() != "live":
            return "GA4_MODE is disabled. Nothing will be requested from Google."
        profile = db.scalar(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id, BrandProfile.deleted_at.is_(None)))
        if profile is None or not (profile.ga4_property_id or "").strip():
            return "The GA4 property id is not saved."
        return ""
    if step_key in {"facebook_post", "instagram_image", "instagram_reel"}:
        if (settings.social_growth_publish_mode or "disabled").strip().lower() != "live":
            return "SOCIAL_GROWTH_PUBLISH_MODE is disabled. Nothing will be published."
        if not (settings.public_api_base_url or "").strip().lower().startswith("https://"):
            return "PUBLIC_API_BASE_URL is not an https address. Publishing stays off until the public endpoint is https."
        platform = "facebook" if step_key == "facebook_post" else "instagram"
        if not any(account.platform == platform for account in accounts):
            return f"No live {platform} account is connected."
        return ""
    return "This step is not part of the acceptance checklist."


def _meta_read_block(mode: str, accounts: list[GrowthAccount]) -> str:
    if (mode or "disabled").strip().lower() != "live":
        return "SOCIAL_GROWTH_INSIGHTS_MODE is disabled. No Meta read will run."
    if not accounts:
        return "No live account is connected. A fixture account cannot verify this step."
    return ""


def _live_accounts(db: Session, tenant_id: UUID) -> list[GrowthAccount]:
    return list(
        db.scalars(
            select(GrowthAccount).where(
                GrowthAccount.tenant_id == tenant_id,
                GrowthAccount.deleted_at.is_(None),
                GrowthAccount.provenance != "fixture",
            )
        ).all()
    )


def _provider_evidence(db: Session, tenant_id: UUID, step_key: str) -> str:
    if step_key == "token_verification":
        for account in _live_accounts(db, tenant_id):
            capabilities = loads(account.capabilities, {})
            if capabilities.get("evidence") == PROVIDER and account.status == "connected":
                return f"Meta verified the {account.platform} account {account.external_id}."
        return ""
    if step_key == "history_import":
        count = _count(db, GrowthMedia, tenant_id, GrowthMedia.provenance == PROVIDER, GrowthMedia.origin == "historical")
        return f"Stored {count} historical post(s) read from Meta." if count else ""
    if step_key == "meta_insights":
        count = _count(
            db,
            GrowthMetricObservation,
            tenant_id,
            GrowthMetricObservation.provenance == PROVIDER,
            GrowthMetricObservation.status.in_(("recorded", "zero")),
        )
        return f"Stored {count} Meta insight reading(s)." if count else ""
    if step_key == "ga4":
        count = _count(db, GrowthTrafficObservation, tenant_id, GrowthTrafficObservation.provenance == PROVIDER)
        return f"Stored {count} GA4 row(s)." if count else ""
    if step_key == "facebook_post":
        count = _publications(db, tenant_id, "facebook", None)
        return f"Meta accepted {count} Facebook post(s)." if count else ""
    if step_key == "instagram_image":
        count = _publications(db, tenant_id, "instagram", "image")
        return f"Meta accepted {count} Instagram image post(s)." if count else ""
    if step_key == "instagram_reel":
        count = _publications(db, tenant_id, "instagram", "reel")
        return f"Meta accepted {count} Instagram Reel(s)." if count else ""
    return ""


def _failure(db: Session, tenant_id: UUID, step_key: str) -> str:
    if step_key != "token_verification":
        return ""
    for account in _live_accounts(db, tenant_id):
        capabilities = loads(account.capabilities, {})
        if capabilities.get("evidence") == "provider_failed" and account.last_error:
            return account.last_error
    return ""


def _count(db: Session, model, tenant_id: UUID, *filters) -> int:
    statement = select(func.count()).select_from(model).where(model.tenant_id == tenant_id, model.deleted_at.is_(None), *filters)
    return int(db.scalar(statement) or 0)


def _publications(db: Session, tenant_id: UUID, platform: str, creative_format: str | None) -> int:
    statement = select(func.count()).select_from(GrowthPublication).where(
        GrowthPublication.tenant_id == tenant_id,
        GrowthPublication.deleted_at.is_(None),
        GrowthPublication.provenance == PROVIDER,
        GrowthPublication.status == "published",
        GrowthPublication.platform == platform,
    )
    if creative_format is not None:
        statement = statement.where(GrowthPublication.format == creative_format)
    return int(db.scalar(statement) or 0)
