"""A prepared demonstration blocks unrelated external work until it is authorized."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ai import AIApproval
from app.models.crm import Lead
from app.models.funnel import PublicFormKey
from app.models.identity import Tenant
from app.models.integrations import ProviderAction
from app.models.lifecycle import MeetingRecord
from app.models.operating_plan import CreativeVersion, DemoScope
from app.providers.social import linkedin_author_urn
from app.services.external_hold import external_action
from app.services.public_forms import form_key_url

PREPARED_BLOCK = "The controlled demonstration is prepared and has not been authorized to execute."
REVIEW_BLOCK = "The demonstration changed after authorization and must be reviewed again."
DEMO_DISCOVERY_BLOCK = "A DEMO workspace cannot run paid discovery without an authorized scope."
DISCOVERY_OUTSIDE = "Paid discovery is outside the authorized scope."
DEMO_PUBLISH_BLOCK = "A DEMO workspace cannot publish without an authorized scope."
DEMO_METRICS_BLOCK = "A DEMO workspace cannot read provider metrics without an authorized scope."
METRICS_OUTSIDE = "Organic metrics are outside the authorized scope."


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def seal_scope(scope: DemoScope) -> None:
    """Record the authorized binding. A later edit makes the digest disagree."""
    scope.binding_digest = _digest(scope)


def _digest(scope: DemoScope) -> str:
    raw = "|".join(
        [
            str(scope.product_id or ""),
            str(scope.plan_id or ""),
            str(scope.version_id or ""),
            scope.content_hash or "",
            scope.form_url or "",
            scope.page_ref or "",
            scope.page_name or "",
            (scope.sender_mailbox or "").casefold(),
            (scope.buyer_email or "").casefold(),
            scope.calendar_id or "",
            scope.allowed_actions or "",
            str(scope.action_limit),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _allowed(scope: DemoScope) -> dict[str, int] | None:
    text = (scope.allowed_actions or "").strip()
    if not text:
        return None
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        return None
    return {str(key): int(value) for key, value in parsed.items()}


def _return_to_review(scope: DemoScope) -> str:
    scope.status = "prepared"
    scope.binding_digest = ""
    return REVIEW_BLOCK


def _material_change(db: Session, scope: DemoScope) -> str:
    if scope.status != "authorized" or not scope.binding_digest:
        return ""
    if _digest(scope) != scope.binding_digest:
        return _return_to_review(scope)
    if scope.version_id is not None:
        version = db.get(CreativeVersion, scope.version_id)
        if version is None or version.content_hash != scope.content_hash:
            return _return_to_review(scope)
    if scope.form_url:
        form = db.scalar(
            select(PublicFormKey)
            .where(
                PublicFormKey.tenant_id == scope.tenant_id,
                PublicFormKey.status == "active",
                PublicFormKey.deleted_at.is_(None),
            )
            .order_by(PublicFormKey.created_at.desc())
        )
        current = form_key_url(form) if form is not None else ""
        if current and current != scope.form_url:
            return _return_to_review(scope)
    if scope.page_ref:
        organization = (get_settings().linkedin_organization_id or "").strip()
        if organization and linkedin_author_urn(organization) != scope.page_ref:
            return _return_to_review(scope)
    return ""


def _used(db: Session, scope: DemoScope, action: str) -> int:
    if action == "social.publish":
        if scope.version_id is None:
            return 0
        version = db.get(CreativeVersion, scope.version_id)
        return 1 if version is not None and version.status == "published" else 0
    if action == "calendar.book":
        buyer = (scope.buyer_email or "").strip().casefold()
        stmt = (
            select(func.count())
            .select_from(MeetingRecord)
            .join(Lead, Lead.id == MeetingRecord.lead_id)
            .where(
                MeetingRecord.tenant_id == scope.tenant_id,
                MeetingRecord.deleted_at.is_(None),
                MeetingRecord.status == "booked",
                MeetingRecord.created_at >= scope.created_at,
            )
        )
        if buyer:
            stmt = stmt.where(func.lower(Lead.email) == buyer)
        return int(db.scalar(stmt) or 0)
    return int(
        db.scalar(
            select(func.count())
            .select_from(ProviderAction)
            .join(AIApproval, AIApproval.id == ProviderAction.approval_id)
            .where(
                ProviderAction.tenant_id == scope.tenant_id,
                ProviderAction.deleted_at.is_(None),
                ProviderAction.status == "CONFIRMED",
                ProviderAction.created_at >= scope.created_at,
                AIApproval.action_type == action,
            )
        )
        or 0
    )


def _provider_health(provider: object) -> dict:
    raw = provider.health() if hasattr(provider, "health") else {}
    if isinstance(raw, dict):
        return raw
    return {
        "is_mock": bool(getattr(raw, "is_mock", False)),
        "connected": bool(getattr(raw, "connected", False)),
    }


def _billable_discovery(provider: object) -> bool:
    health = _provider_health(provider)
    if health.get("is_mock"):
        return False
    if health.get("connected") is False:
        return False
    return True


def discovery_execution_block(db: Session, tenant_id: UUID, provider: object) -> str:
    """Billable discovery on a DEMO tenant requires an authorized scope.

    A missing scope is not permission. A prepared scope is not permission.
    Mock and unconfigured providers stay available. Other operating modes
    keep their current path.
    """
    tenant = db.get(Tenant, tenant_id)
    mode = ((tenant.operating_mode if tenant is not None else "") or "DEMO").strip().upper()
    if mode != "DEMO":
        return ""
    if not _billable_discovery(provider):
        return ""
    scope = open_demo_scope(db, tenant_id)
    if scope is None:
        return DEMO_DISCOVERY_BLOCK
    if scope.status != "authorized":
        return PREPARED_BLOCK
    changed = _material_change(db, scope)
    if changed:
        return changed
    expires = _aware(scope.expires_at)
    if expires is not None and expires < datetime.now(UTC):
        return "The demonstration scope has expired. Nothing was sent."
    allowed = _allowed(scope)
    if allowed is None or int(allowed.get("discovery.search") or 0) <= 0:
        return DISCOVERY_OUTSIDE
    return ""


def organic_metrics_block(db: Session, tenant_id: UUID) -> str:
    """A DEMO tenant does not call a live metrics API unless a scope allows it.

    A missing or prepared scope is not permission. This does not change the scope.
    """
    tenant = db.get(Tenant, tenant_id)
    mode = ((tenant.operating_mode if tenant is not None else "") or "DEMO").strip().upper()
    if mode != "DEMO":
        return ""
    scope = open_demo_scope(db, tenant_id)
    if scope is None:
        return DEMO_METRICS_BLOCK
    if scope.status != "authorized":
        return PREPARED_BLOCK
    changed = _material_change(db, scope)
    if changed:
        return changed
    expires = _aware(scope.expires_at)
    if expires is not None and expires < datetime.now(UTC):
        return "The demonstration scope has expired. Nothing was sent."
    allowed = _allowed(scope)
    if allowed is None or int(allowed.get("organic.metrics") or 0) <= 0:
        return METRICS_OUTSIDE
    return ""


def open_demo_scope(db: Session, tenant_id: UUID) -> DemoScope | None:
    return db.scalar(
        select(DemoScope)
        .where(
            DemoScope.tenant_id == tenant_id,
            DemoScope.deleted_at.is_(None),
            DemoScope.status.in_(["prepared", "authorized"]),
        )
        .order_by(DemoScope.created_at.desc())
    )


def _operating_mode(db: Session, tenant_id: UUID) -> str:
    tenant = db.get(Tenant, tenant_id)
    return ((tenant.operating_mode if tenant is not None else "") or "DEMO").strip().upper()


def external_execution_block(
    db: Session,
    *,
    tenant_id: UUID,
    action: str,
    recipient: str = "",
    target_id: str = "",
    channel: str = "",
    real_effect: bool = False,
) -> str:
    if not external_action(action):
        return ""
    scope = open_demo_scope(db, tenant_id)
    if scope is None:
        if real_effect and action == "social.publish" and _operating_mode(db, tenant_id) == "DEMO":
            return DEMO_PUBLISH_BLOCK
        return ""
    if scope.status == "prepared":
        return PREPARED_BLOCK
    changed = _material_change(db, scope)
    if changed:
        return changed
    if action.startswith("ads.") or action.startswith("voice."):
        return "Ads and voice stay outside this demonstration. No activation or dial was sent."
    allowed = _allowed(scope)
    if allowed is not None and action.startswith("sequence."):
        return "Sequence outreach is outside this demonstration."
    if allowed is not None and action not in allowed:
        return "That action is outside the controlled demonstration."
    expires = _aware(scope.expires_at)
    if expires is not None and expires < datetime.now(UTC):
        return "The demonstration scope has expired. Nothing was sent."
    if allowed is None:
        used = int(
            db.scalar(
                select(func.count())
                .select_from(ProviderAction)
                .where(
                    ProviderAction.tenant_id == tenant_id,
                    ProviderAction.deleted_at.is_(None),
                    ProviderAction.status == "CONFIRMED",
                    ProviderAction.created_at >= scope.created_at,
                )
            )
            or 0
        )
        if used >= scope.action_limit:
            return "The demonstration action limit is reached. Nothing was sent."
    elif _used(db, scope, action) >= allowed[action]:
        return "The demonstration action limit is reached. Nothing was sent."
    buyer = (scope.buyer_email or "").strip().casefold()
    if action.startswith("social"):
        if scope.version_id is None or not target_id or target_id != str(scope.version_id):
            return "That creative version is outside the controlled demonstration."
        if scope.channel and channel and channel != scope.channel:
            return "That social channel is outside the controlled demonstration."
        return ""
    if not buyer or recipient.strip().casefold() != buyer:
        return "The recipient is outside the controlled demonstration."
    return ""
