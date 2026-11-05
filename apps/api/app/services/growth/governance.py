"""Execution authorization for publishing.

A post publishes only under an active bounded grant for its platform, or after
a person approves that exact creative in the decision inbox. The action type
starts with `social.` so the demonstration guard, the social channel pause,
and stale-work holds apply to it like any other social action.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.execution import AuthorizationGrant
from app.models.growth import GrowthAccount, GrowthCalendarItem, GrowthCreative, GrowthPublication
from app.services.audit import write_audit
from app.services.growth.common import PUBLISHABLE_PLATFORMS, aware, dumps, iso, loads, now

WORKFLOW = "social_growth"
ACTION = "social.growth_publish"


def active_grant(db: Session, tenant_id: UUID, platform: str) -> AuthorizationGrant | None:
    moment = now()
    rows = db.scalars(
        select(AuthorizationGrant).where(
            AuthorizationGrant.tenant_id == tenant_id,
            AuthorizationGrant.deleted_at.is_(None),
            AuthorizationGrant.status == "active",
            AuthorizationGrant.workflow == WORKFLOW,
            AuthorizationGrant.channel == platform,
            AuthorizationGrant.mode == "bounded_autopilot",
        )
    ).all()
    live = [row for row in rows if aware(row.expires_at) is None or aware(row.expires_at) > moment]
    return live[0] if live else None


def published_last_day(db: Session, tenant_id: UUID, *, platform: str = "", account_id: UUID | None = None) -> int:
    stmt = select(func.count()).select_from(GrowthPublication).where(
        GrowthPublication.tenant_id == tenant_id,
        GrowthPublication.deleted_at.is_(None),
        GrowthPublication.status == "published",
        GrowthPublication.published_at >= now() - timedelta(hours=24),
    )
    if platform:
        stmt = stmt.where(GrowthPublication.platform == platform)
    if account_id is not None:
        stmt = stmt.where(GrowthPublication.account_id == account_id)
    return int(db.scalar(stmt) or 0)


def approved_request(db: Session, tenant_id: UUID, item: GrowthCalendarItem, creative: GrowthCreative) -> AIApproval | None:
    rows = db.scalars(
        select(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.action_type == ACTION,
            AIApproval.entity_type == "growth_calendar_item",
            AIApproval.entity_id == str(item.id),
            AIApproval.status == "approved",
            AIApproval.deleted_at.is_(None),
        )
    ).all()
    for row in rows:
        if loads(row.payload_json, {}).get("content_hash") == creative.content_hash:
            return row
    return None


def publish_authorization(db: Session, tenant_id: UUID, item: GrowthCalendarItem, creative: GrowthCreative, account: GrowthAccount) -> tuple[str, str, str]:
    """Return execute, approval, or blocked, with the reason and the grant or approval reference."""
    grant = active_grant(db, tenant_id, account.platform)
    if grant is not None:
        if grant.volume_cap > 0 and published_last_day(db, tenant_id, platform=account.platform) >= grant.volume_cap:
            return "approval", f"The {account.platform} grant allows {grant.volume_cap} post(s) in 24 hours and that is reached.", ""
        return "execute", f"Authorized by grant {grant.name}.", f"grant:{grant.id}"
    approval = approved_request(db, tenant_id, item, creative)
    if approval is not None:
        return "execute", "Approved in the decision inbox.", f"approval:{approval.id}"
    return "approval", "No execution grant covers this platform. A person must approve this post in the decision inbox.", ""


def request_publish_approval(db: Session, *, tenant_id: UUID, actor_id: UUID | None, item: GrowthCalendarItem, creative: GrowthCreative, account: GrowthAccount) -> AIApproval:
    key = f"{ACTION}:{item.id}:{creative.content_hash[:16]}"
    existing = db.scalar(select(AIApproval).where(AIApproval.tenant_id == tenant_id, AIApproval.idempotency_key == key, AIApproval.deleted_at.is_(None)))
    if existing is not None:
        return existing
    label = account.name or account.username or account.external_id
    row = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type=ACTION,
        title=f"Publish {creative.format} to {account.platform.title()} {label} on {item.local_date}"[:200],
        payload_json=dumps(
            {
                "item_id": str(item.id),
                "creative_id": str(creative.id),
                "content_hash": creative.content_hash,
                "account_id": str(account.id),
                "platform": account.platform,
                "format": creative.format,
                "planned_for": iso(item.planned_for),
                "message": creative.caption,
                "who": label,
                "why": "The approved strategy scheduled this post and no execution grant covers the platform.",
                "evidence": f"Creative version {creative.version}. Quality {creative.quality_state}. Facts: {', '.join(loads(creative.fact_ids_json, [])[:3])}.",
                "risk": "Approving publishes this exact creative to the named account at or after its planned time.",
                "expected_outcome": "One post on one account. Nothing else is published.",
            }
        ),
        status="pending",
        entity_type="growth_calendar_item",
        entity_id=str(item.id),
        idempotency_key=key,
        expires_at=(aware(item.planned_for) or now()) + timedelta(days=2),
    )
    db.add(row)
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.publish_approval_requested", entity_type="ai_approval", entity_id=str(row.id), after={"item_id": str(item.id), "creative_id": str(creative.id)}, actor_type="human" if actor_id else "ai")
    return row


def withdraw_publish_requests(db: Session, *, tenant_id: UUID, actor_id: UUID | None, item_id: UUID, reason: str) -> int:
    rows = db.scalars(
        select(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.action_type == ACTION,
            AIApproval.entity_type == "growth_calendar_item",
            AIApproval.entity_id == str(item_id),
            AIApproval.status == "pending",
            AIApproval.deleted_at.is_(None),
        )
    ).all()
    for row in rows:
        row.status = "cancelled"
        write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.publish_approval_withdrawn", entity_type="ai_approval", entity_id=str(row.id), before={"status": "pending"}, after={"status": "cancelled", "reason": reason}, actor_type="human" if actor_id else "ai")
    db.flush()
    return len(rows)


def create_grant(db: Session, *, tenant_id: UUID, actor_id: UUID, platform: str, volume_cap: int, days: int, name: str = "") -> AuthorizationGrant:
    if platform not in PUBLISHABLE_PLATFORMS:
        raise HTTPException(status_code=422, detail="Choose facebook or instagram.")
    if not 1 <= volume_cap <= 25:
        raise HTTPException(status_code=422, detail="A grant needs a daily cap between 1 and 25 posts.")
    if not 1 <= days <= 90:
        raise HTTPException(status_code=422, detail="A grant must expire within 1 to 90 days.")
    existing = active_grant(db, tenant_id, platform)
    if existing is not None:
        existing.status = "superseded"
    row = AuthorizationGrant(
        tenant_id=tenant_id,
        created_by=actor_id,
        name=(name.strip() or f"Social growth {platform} publishing")[:160],
        mode="bounded_autopilot",
        workflow=WORKFLOW,
        channel=platform,
        volume_cap=volume_cap,
        status="active",
        expires_at=now() + timedelta(days=days),
    )
    db.add(row)
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.grant_create", entity_type="authorization_grant", entity_id=str(row.id), after={"platform": platform, "volume_cap": volume_cap, "expires_at": iso(row.expires_at)})
    return row


def revoke_grant(db: Session, *, tenant_id: UUID, actor_id: UUID, grant_id: UUID) -> AuthorizationGrant:
    row = db.scalar(select(AuthorizationGrant).where(AuthorizationGrant.tenant_id == tenant_id, AuthorizationGrant.id == grant_id, AuthorizationGrant.workflow == WORKFLOW, AuthorizationGrant.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    before = row.status
    row.status = "revoked"
    db.flush()
    write_audit(db, tenant_id=tenant_id, actor_id=actor_id, action="growth.grant_revoke", entity_type="authorization_grant", entity_id=str(row.id), before={"status": before}, after={"status": "revoked"})
    return row


def grants(db: Session, tenant_id: UUID) -> list[dict]:
    rows = db.scalars(
        select(AuthorizationGrant)
        .where(AuthorizationGrant.tenant_id == tenant_id, AuthorizationGrant.workflow == WORKFLOW, AuthorizationGrant.deleted_at.is_(None))
        .order_by(AuthorizationGrant.created_at.desc())
        .limit(20)
    ).all()
    moment = now()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "platform": row.channel,
            "mode": row.mode,
            "volume_cap": row.volume_cap,
            "status": "expired" if row.status == "active" and aware(row.expires_at) is not None and aware(row.expires_at) <= moment else row.status,
            "expires_at": iso(row.expires_at),
            "published_last_24h": published_last_day(db, tenant_id, platform=row.channel),
        }
        for row in rows
    ]
