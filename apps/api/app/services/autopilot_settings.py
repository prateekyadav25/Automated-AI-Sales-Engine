from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.autonomy import AutopilotSettings
from app.models.crm import Lead
from app.models.identity import FeatureFlag


def _flag(db: Session, tenant_id: UUID, key: str) -> FeatureFlag | None:
    return db.scalar(select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id, FeatureFlag.key == key))


def _upsert_flag(db: Session, *, tenant_id: UUID, key: str, enabled: bool, description: str) -> None:
    row = _flag(db, tenant_id, key)
    if row is None:
        db.add(FeatureFlag(tenant_id=tenant_id, key=key, enabled=enabled, description=description))
        return
    row.enabled = enabled


def get_or_create_settings(db: Session, *, tenant_id: UUID, actor_id: UUID | None = None) -> AutopilotSettings:
    row = db.scalar(select(AutopilotSettings).where(AutopilotSettings.tenant_id == tenant_id, AutopilotSettings.deleted_at.is_(None)))
    if row is not None:
        return row
    autopilot_flag = _flag(db, tenant_id, "ENABLE_AUTOPILOT")
    discovery_flag = _flag(db, tenant_id, "ENABLE_LEAD_DISCOVERY")
    row = AutopilotSettings(
        tenant_id=tenant_id,
        created_by=actor_id,
        enabled=True if autopilot_flag is None else bool(autopilot_flag.enabled),
        discovery_enabled=True if discovery_flag is None else bool(discovery_flag.enabled),
    )
    db.add(row)
    db.flush()
    _upsert_flag(db, tenant_id=tenant_id, key="ENABLE_AUTOPILOT", enabled=row.enabled, description="Persisted autonomous cycle")
    _upsert_flag(
        db,
        tenant_id=tenant_id,
        key="ENABLE_LEAD_DISCOVERY",
        enabled=row.discovery_enabled,
        description="Apify or labeled mock discovery",
    )
    return row


def sync_flags(db: Session, settings: AutopilotSettings) -> None:
    _upsert_flag(
        db,
        tenant_id=settings.tenant_id,
        key="ENABLE_AUTOPILOT",
        enabled=settings.enabled,
        description="Persisted autonomous cycle",
    )
    _upsert_flag(
        db,
        tenant_id=settings.tenant_id,
        key="ENABLE_LEAD_DISCOVERY",
        enabled=settings.discovery_enabled,
        description="Apify or labeled mock discovery",
    )


def is_enabled(db: Session, tenant_id: UUID) -> bool:
    row = db.scalar(select(AutopilotSettings).where(AutopilotSettings.tenant_id == tenant_id, AutopilotSettings.deleted_at.is_(None)))
    if row is not None:
        return bool(row.enabled)
    flag = _flag(db, tenant_id, "ENABLE_AUTOPILOT")
    return bool(flag and flag.enabled)


def apply_settings_update(db: Session, settings: AutopilotSettings, payload: dict) -> AutopilotSettings:
    allowed = {
        "enabled",
        "market_monitoring_enabled",
        "discovery_enabled",
        "research_enabled",
        "enrichment_enabled",
        "lead_scoring_enabled",
        "qualification_enabled",
        "campaign_planning_enabled",
        "sequence_enrollment_enabled",
        "outreach_preparation_enabled",
        "meeting_preparation_enabled",
        "deal_monitoring_enabled",
        "proposal_preparation_enabled",
        "customer_health_enabled",
        "renewal_enabled",
        "expansion_enabled",
        "advocacy_enabled",
        "max_leads_per_day",
        "email_approval_required",
        "voice_approval_required",
        "ad_spend_approval_required",
        "auto_create_internal_tasks",
        "auto_update_scores",
        "quiet_hours_start",
        "quiet_hours_end",
        "timezone",
        "daily_budget_limit",
        "monthly_budget_limit",
        "minimum_lead_score",
        "minimum_intent_score",
        "minimum_expansion_score",
    }
    for key, value in payload.items():
        if key in allowed and value is not None:
            setattr(settings, key, value)
    sync_flags(db, settings)
    return settings


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    parts = (value or "").split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def in_quiet_hours(settings: AutopilotSettings, now: datetime | None = None) -> bool:
    start = _parse_hhmm(settings.quiet_hours_start)
    end = _parse_hhmm(settings.quiet_hours_end)
    if start is None or end is None:
        return False
    try:
        zone = ZoneInfo(settings.timezone or "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    local = current.astimezone(zone)
    minutes = local.hour * 60 + local.minute
    start_m = start[0] * 60 + start[1]
    end_m = end[0] * 60 + end[1]
    if start_m == end_m:
        return False
    if start_m < end_m:
        return start_m <= minutes < end_m
    return minutes >= start_m or minutes < end_m


def discovered_today(db: Session, tenant_id: UUID) -> int:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(
                Lead.tenant_id == tenant_id,
                Lead.deleted_at.is_(None),
                Lead.source == "ai_discovery",
                Lead.created_at >= start,
            )
        )
        or 0
    )


def at_daily_lead_cap(db: Session, settings: AutopilotSettings) -> bool:
    if settings.max_leads_per_day <= 0:
        return False
    return discovered_today(db, settings.tenant_id) >= settings.max_leads_per_day
