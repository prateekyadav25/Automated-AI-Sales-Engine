from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.autonomy import AutopilotSettings
from app.models.integrations import EmailMessage


def emails_sent_today(db: Session, tenant_id: UUID) -> int:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(
                EmailMessage.tenant_id == tenant_id,
                EmailMessage.deleted_at.is_(None),
                EmailMessage.direction == "outbound",
                EmailMessage.status == "SENT",
                EmailMessage.sent_at >= start,
            )
        )
        or 0
    )


def emails_sent_to_lead_today(db: Session, tenant_id: UUID, lead_id: UUID) -> int:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(
                EmailMessage.tenant_id == tenant_id,
                EmailMessage.deleted_at.is_(None),
                EmailMessage.direction == "outbound",
                EmailMessage.status == "SENT",
                EmailMessage.lead_id == lead_id,
                EmailMessage.sent_at >= start,
            )
        )
        or 0
    )


def last_outbound_at(db: Session, tenant_id: UUID, lead_id: UUID) -> datetime | None:
    return db.scalar(
        select(EmailMessage.sent_at)
        .where(
            EmailMessage.tenant_id == tenant_id,
            EmailMessage.deleted_at.is_(None),
            EmailMessage.direction == "outbound",
            EmailMessage.status == "SENT",
            EmailMessage.lead_id == lead_id,
        )
        .order_by(EmailMessage.sent_at.desc())
    )


def outreach_limit_reason(db: Session, settings: AutopilotSettings, lead_id: UUID) -> str | None:
    if settings.max_emails_per_day > 0 and emails_sent_today(db, settings.tenant_id) >= settings.max_emails_per_day:
        return "Daily email cap reached"
    if (
        settings.max_emails_per_contact_per_day > 0
        and emails_sent_to_lead_today(db, settings.tenant_id, lead_id) >= settings.max_emails_per_contact_per_day
    ):
        return "Per-contact daily email cap reached"
    if settings.minimum_hours_between_outreach > 0:
        previous = last_outbound_at(db, settings.tenant_id, lead_id)
        if previous is not None:
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=UTC)
            gap = datetime.now(UTC) - previous
            if gap < timedelta(hours=settings.minimum_hours_between_outreach):
                return "Minimum hours between outreach not elapsed"
    return None
