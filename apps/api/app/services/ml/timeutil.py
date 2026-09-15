from datetime import UTC, datetime


def aware_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)


def truncate_seconds(value: datetime) -> datetime:
    stamped = aware_dt(value) or now_utc()
    return stamped.replace(microsecond=0)
