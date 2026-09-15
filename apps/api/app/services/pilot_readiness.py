from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.config import get_settings
from app.models.identity import FeatureFlag, Permission, RolePermission, Tenant, User, UserRole
from app.models.integrations import ProviderAccount
from app.services.audit import write_audit
from app.services.autopilot_settings import get_or_create_settings
from app.services.provider_provision import provision_env_credentials
from app.services.provider_resolve import resolve_channel
from app.services.rbac import user_permissions
from app.services.scheduler_health import beat_status

CRITICAL_PILOT = {"authentication", "approvals", "emergency_stop", "migrations"}
CRITICAL_PRODUCTION = CRITICAL_PILOT | {"rls", "backup", "malware", "encryption", "callbacks", "metrics_auth"}


def _alembic_head() -> str:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head() or ""


def _db_revision(db: Session) -> str:
    try:
        row = db.execute(text("SELECT version_num FROM alembic_version")).first()
    except Exception:
        return ""
    return str(row[0]) if row else ""


def _has_approver(db: Session, tenant_id: UUID) -> bool:
    users = db.scalars(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True))).all()
    for user in users:
        if "ai.approvals.decide" in user_permissions(db, user):
            return True
    permission = db.scalar(select(Permission).where(Permission.key == "ai.approvals.decide"))
    if permission is None:
        return False
    return (
        db.scalar(
            select(UserRole.user_id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(User, User.id == UserRole.user_id)
            .where(RolePermission.permission_id == permission.id, User.tenant_id == tenant_id, User.is_active.is_(True))
        )
        is not None
    )


def _item(key: str, state: str, detail: str, required: bool) -> dict:
    return {"key": key, "state": state, "detail": detail, "required": required}


def evaluate_readiness(db: Session, *, tenant_id: UUID) -> dict:
    settings = get_settings()
    tenant = db.get(Tenant, tenant_id)
    autopilot = get_or_create_settings(db, tenant_id=tenant_id)
    mode = (tenant.operating_mode if tenant else "DEMO") or "DEMO"
    items: list[dict] = []

    head = _alembic_head()
    current = _db_revision(db)
    if not current and settings.database_url.startswith("sqlite"):
        items.append(_item("migrations", "READY", "SQLite create_all path; Alembic head is 016", True))
    elif current == head and head:
        items.append(_item("migrations", "READY", f"Database revision {current}", True))
    else:
        items.append(_item("migrations", "BLOCKER", f"Database revision {current or 'none'} vs head {head}", True))

    items.append(_item("authentication", "READY", "JWT and refresh families are in product", True))
    items.append(
        _item(
            "approvals",
            "READY" if _has_approver(db, tenant_id) else "BLOCKER",
            "An approval administrator exists" if _has_approver(db, tenant_id) else "No user with ai.approvals.decide",
            True,
        )
    )
    items.append(_item("emergency_stop", "READY", "Tenant and global emergency stop controls exist", True))

    rls_ok = settings.database_url.startswith("postgresql") and bool(settings.database_admin_url)
    items.append(
        _item(
            "rls",
            "READY" if rls_ok else ("OPTIONAL" if not settings.is_production else "BLOCKER"),
            "Postgres admin URL configured" if rls_ok else "RLS requires Postgres and DATABASE_ADMIN_URL",
            settings.is_production,
        )
    )
    backup_ok = bool(settings.database_admin_url)
    items.append(
        _item(
            "backup",
            "READY" if backup_ok else ("OPTIONAL" if not settings.is_production else "BLOCKER"),
            "DATABASE_ADMIN_URL can dump Postgres" if backup_ok else "Backup target is not configured",
            settings.is_production,
        )
    )

    email = resolve_channel(db, tenant_id, "email")
    if settings.email_provider == "mock":
        items.append(_item("email", "MOCK", "EMAIL_PROVIDER=mock", False))
    elif email.mode == "LIVE":
        items.append(_item("email", "READY", email.reason, True if mode != "DEMO" else False))
    else:
        outbound = bool(autopilot.outreach_preparation_enabled or autopilot.sequence_enrollment_enabled)
        items.append(_item("email", "BLOCKER" if outbound and mode != "DEMO" else "NOT_CONFIGURED", email.reason, outbound and mode != "DEMO"))

    for key, optional in [
        ("calendar", True),
        ("discovery", True),
        ("linkedin", True),
        ("vapi", True),
        ("whatsapp", True),
    ]:
        resolved = resolve_channel(db, tenant_id, key if key != "linkedin" else "linkedin")
        state = resolved.mode if resolved.mode in {"MOCK", "NOT_CONFIGURED"} else "READY"
        if resolved.mode == "LIVE":
            state = "READY"
        items.append(_item(key if key != "linkedin" else "ads", state, resolved.reason, False))

    voice = resolve_channel(db, tenant_id, "twilio")
    items.append(_item("voice", "READY" if voice.mode == "LIVE" else voice.mode, voice.reason, False))
    items.append(_item("usage", "READY" if autopilot.usage_live_enabled else "OPTIONAL", "Generic signed usage webhook", False))
    items.append(_item("support", "OPTIONAL", "Generic signed support webhook; vendor HTTP stays NOT_CONFIGURED", False))
    items.append(_item("finance", "OPTIONAL", "Generic signed finance webhook; Stripe stays NOT_CONFIGURED", False))
    items.append(_item("autopilot", "READY" if autopilot.enabled and not autopilot.emergency_stop else "PARTIAL", "Autopilot settings exist", False))
    beat = beat_status(db)
    items.append(
        _item(
            "observability",
            "BLOCKER" if beat["scheduler_unhealthy"] and mode in {"PILOT", "PRODUCTION"} else ("READY" if not beat["scheduler_unhealthy"] else "OPTIONAL"),
            f"scheduler {beat['state']}",
            False,
        )
    )
    malware = (settings.malware_scanner or "").strip()
    items.append(
        _item(
            "malware",
            "READY" if malware else ("OPTIONAL" if mode != "PRODUCTION" else "BLOCKER"),
            "Scanner configured" if malware else "Malware scanner is NOT_CONFIGURED",
            mode == "PRODUCTION",
        )
    )
    encryption_ok = bool((settings.token_encryption_key or "").strip())
    items.append(
        _item(
            "encryption",
            "READY" if encryption_ok else ("OPTIONAL" if mode != "PRODUCTION" else "BLOCKER"),
            "TOKEN_ENCRYPTION_KEY is set" if encryption_ok else "TOKEN_ENCRYPTION_KEY is empty; Fernet still derives from SECRET_KEY",
            mode == "PRODUCTION",
        )
    )
    https_ok = (settings.public_api_base_url or "").strip().lower().startswith("https://")
    items.append(
        _item(
            "callbacks",
            "READY" if https_ok else ("OPTIONAL" if mode != "PRODUCTION" else "BLOCKER"),
            "PUBLIC_API_BASE_URL is HTTPS" if https_ok else "Provider callbacks need a public HTTPS PUBLIC_API_BASE_URL",
            mode == "PRODUCTION",
        )
    )
    metrics_ok = bool((settings.metrics_token or "").strip())
    items.append(
        _item(
            "metrics_auth",
            "READY" if metrics_ok else ("OPTIONAL" if mode != "PRODUCTION" else "BLOCKER"),
            "METRICS_TOKEN is set" if metrics_ok else "METRICS_TOKEN is empty",
            mode == "PRODUCTION",
        )
    )

    blockers = [item for item in items if item["state"] == "BLOCKER" and item["required"]]
    return {
        "operating_mode": mode,
        "environment": settings.environment,
        "can_activate_pilot": not any(item["key"] in CRITICAL_PILOT and item["state"] == "BLOCKER" for item in items),
        "can_activate_production": not any(item["key"] in CRITICAL_PRODUCTION and item["state"] == "BLOCKER" for item in items),
        "blockers": [item["key"] for item in blockers],
        "items": items,
        "connected_accounts": db.scalar(select(ProviderAccount).where(ProviderAccount.tenant_id == tenant_id, ProviderAccount.deleted_at.is_(None))) is not None,
    }


class PilotActivationError(ValueError):
    pass


def activate_mode(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    target: str,
    reason: str,
) -> Tenant:
    if target not in {"DEMO", "PILOT", "PRODUCTION"}:
        raise PilotActivationError("Unknown operating mode")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise PilotActivationError("Tenant not found")
    provision_env_credentials(db, tenant_id=tenant_id, actor_id=actor_id)
    report = evaluate_readiness(db, tenant_id=tenant_id)
    if target == "PILOT" and not report["can_activate_pilot"]:
        raise PilotActivationError(f"PILOT blocked: {', '.join(report['blockers']) or 'critical checks failed'}")
    if target == "PRODUCTION" and not report["can_activate_production"]:
        raise PilotActivationError(f"PRODUCTION blocked: {', '.join(report['blockers']) or 'critical checks failed'}")
    previous = tenant.operating_mode
    tenant.operating_mode = target
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    if target == "PILOT":
        settings.allow_deployment_provider_defaults = False
        settings.max_emails_per_day = min(settings.max_emails_per_day, 25)
        settings.max_leads_per_day = min(settings.max_leads_per_day, 15)
        settings.max_calls_per_day = min(settings.max_calls_per_day, 5)
        settings.email_approval_required = True
        settings.voice_approval_required = True
        settings.ad_spend_approval_required = True
        if not settings.ai_daily_budget:
            settings.ai_daily_budget = 10
    if target == "PRODUCTION":
        settings.allow_deployment_provider_defaults = False
        settings.allow_unscanned_uploads = False
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="pilot.activate",
        entity_type="tenant",
        entity_id=str(tenant_id),
        before={"operating_mode": previous},
        after={"operating_mode": target, "reason": reason},
    )
    return tenant


def export_config(db: Session, *, tenant_id: UUID) -> dict:
    tenant = db.get(Tenant, tenant_id)
    settings = get_or_create_settings(db, tenant_id=tenant_id)
    flags = [
        {"key": row.key, "enabled": row.enabled}
        for row in db.scalars(select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id)).all()
    ]
    return {
        "operating_mode": tenant.operating_mode if tenant else "DEMO",
        "environment": get_settings().environment,
        "policy_version": settings.current_policy_version,
        "autopilot": {
            "enabled": settings.enabled,
            "emergency_stop": settings.emergency_stop,
            "max_emails_per_day": settings.max_emails_per_day,
            "max_leads_per_day": settings.max_leads_per_day,
            "max_calls_per_day": settings.max_calls_per_day,
            "ai_daily_budget": float(settings.ai_daily_budget or 0),
            "allow_deployment_provider_defaults": settings.allow_deployment_provider_defaults,
            "quiet_hours_start": settings.quiet_hours_start,
            "quiet_hours_end": settings.quiet_hours_end,
        },
        "providers": {
            key: resolve_channel(db, tenant_id, key).mode
            for key in ("email", "calendar", "discovery", "linkedin", "meta", "twilio", "vapi", "exotel", "openai", "whatsapp")
        },
        "flags": flags,
    }
