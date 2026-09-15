import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.integrations import ProviderAction, ProviderHealthState
from app.services.audit import write_audit
from app.services.provider_metrics import PROVIDER_DEAD_LETTERS, PROVIDER_RETRIES, observe_request
from app.services.query import paginate

CIRCUIT_THRESHOLD = 5
CIRCUIT_COOLDOWN = timedelta(minutes=5)
MAX_ATTEMPTS = 5
DEFAULT_ALERTS = {
    "provider_failure_spike": 10,
    "inbox_backlog": 50,
    "dead_letters": 1,
    "high_retry_rate": 20,
    "webhook_failures": 5,
}


def classify_http(status_code: int, *, timeout: bool = False) -> str:
    if timeout:
        return "TRANSIENT"
    if status_code == 429:
        return "RATE_LIMIT"
    if status_code in {401, 403}:
        return "AUTHENTICATION"
    if 400 <= status_code < 500:
        return "PERMANENT"
    if status_code >= 500 or status_code == 0:
        return "TRANSIENT"
    return ""


def redact(text: str) -> str:
    lowered = (text or "").lower()
    if any(token in lowered for token in ("bearer ", "access_token", "auth_token", "api_key", "secret")):
        return "redacted"
    return (text or "")[:400]


def get_health_state(db: Session, *, tenant_id: UUID, provider: str) -> ProviderHealthState | None:
    return db.scalar(
        select(ProviderHealthState).where(
            ProviderHealthState.tenant_id == tenant_id,
            ProviderHealthState.provider == provider,
            ProviderHealthState.deleted_at.is_(None),
        )
    )


def is_circuit_open(db: Session, *, tenant_id: UUID, provider: str, now: datetime | None = None) -> bool:
    row = get_health_state(db, tenant_id=tenant_id, provider=provider)
    if row is None or row.state != "DEGRADED" or row.opened_at is None:
        return False
    current = now or datetime.now(UTC)
    opened = row.opened_at if row.opened_at.tzinfo else row.opened_at.replace(tzinfo=UTC)
    return current - opened < CIRCUIT_COOLDOWN


def record_provider_result(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    provider: str,
    action: str,
    ok: bool,
    failure_class: str = "",
    error: str = "",
    latency_s: float | None = None,
) -> ProviderHealthState:
    observe_request(provider=provider, action=action, ok=ok, failure_class=failure_class, latency_s=latency_s)
    row = get_health_state(db, tenant_id=tenant_id, provider=provider)
    if row is None:
        row = ProviderHealthState(tenant_id=tenant_id, created_by=actor_id, provider=provider)
        db.add(row)
        db.flush()
    now = datetime.now(UTC)
    if ok:
        row.consecutive_failures = 0
        row.last_success_at = now
        row.state = "CONNECTED"
        row.opened_at = None
        row.last_error_summary = ""
    else:
        row.consecutive_failures += 1
        row.last_failure_at = now
        row.last_error_summary = redact(error)
        if failure_class == "RATE_LIMIT":
            row.state = "RATE_LIMITED"
        elif failure_class == "AUTHENTICATION":
            row.state = "ERROR"
        elif failure_class == "CONFIGURATION":
            row.state = "NOT_CONFIGURED"
        elif row.consecutive_failures >= CIRCUIT_THRESHOLD:
            row.state = "DEGRADED"
            row.opened_at = row.opened_at or now
        else:
            row.state = "ERROR"
    return row


def begin_action(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    action_type: str,
    idempotency_key: str,
    provider: str,
    approval_id: UUID | None = None,
    run_id: UUID | None = None,
    entity_type: str = "",
    entity_id: str = "",
    request_summary: str = "",
) -> ProviderAction:
    existing = db.scalar(
        select(ProviderAction).where(
            ProviderAction.tenant_id == tenant_id,
            ProviderAction.idempotency_key == idempotency_key,
            ProviderAction.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing
    row = ProviderAction(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_type=action_type,
        approval_id=approval_id,
        run_id=run_id,
        entity_type=entity_type,
        entity_id=entity_id,
        provider=provider,
        idempotency_key=idempotency_key,
        status="REQUESTED",
        request_summary=redact(request_summary),
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        recovered = db.scalar(
            select(ProviderAction).where(
                ProviderAction.tenant_id == tenant_id,
                ProviderAction.idempotency_key == idempotency_key,
                ProviderAction.deleted_at.is_(None),
            )
        )
        if recovered is None:
            raise
        return recovered
    return row


def confirm_action(row: ProviderAction, *, provider: str, external_id: str, response_summary: str = "") -> None:
    row.status = "CONFIRMED"
    row.provider = provider
    row.external_id = external_id
    row.failure_class = ""
    row.last_error = ""
    row.response_summary = redact(response_summary)
    row.attempts = max(row.attempts, 1)


def fail_action(row: ProviderAction, *, failure_class: str, error: str, retryable: bool) -> None:
    row.attempts += 1
    row.failure_class = failure_class
    row.last_error = redact(error)
    if failure_class in {"PERMANENT", "CONFIGURATION", "AUTHENTICATION"} or not retryable or row.attempts >= MAX_ATTEMPTS:
        row.status = "DEAD_LETTER"
        row.next_retry_at = None
        PROVIDER_DEAD_LETTERS.labels(provider=(row.provider or "unknown")[:40]).inc()
        return
    row.status = "RETRYING"
    row.next_retry_at = datetime.now(UTC) + timedelta(seconds=min(300, 15 * (2 ** max(row.attempts - 1, 0))))
    PROVIDER_RETRIES.labels(provider=(row.provider or "unknown")[:40], action=(row.action_type or "unknown")[:40]).inc()


def block_action(row: ProviderAction, *, reason: str, failure_class: str = "CONFIGURATION") -> None:
    row.status = "BLOCKED"
    row.failure_class = failure_class
    row.last_error = redact(reason)


def list_actions(
    db: Session,
    *,
    tenant_id: UUID,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[ProviderAction], int]:
    stmt = (
        select(ProviderAction)
        .where(ProviderAction.tenant_id == tenant_id, ProviderAction.deleted_at.is_(None))
        .order_by(ProviderAction.created_at.desc())
    )
    if status:
        stmt = stmt.where(ProviderAction.status == status)
    rows, total = paginate(db, stmt, page, page_size)
    return list(rows), total


def action_counts(db: Session, *, tenant_id: UUID, provider: str = "") -> dict[str, int]:
    stmt = select(ProviderAction.status, func.count()).where(
        ProviderAction.tenant_id == tenant_id,
        ProviderAction.deleted_at.is_(None),
    )
    if provider:
        stmt = stmt.where(ProviderAction.provider == provider)
    rows = db.execute(stmt.group_by(ProviderAction.status)).all()
    return {str(status): int(count) for status, count in rows}


def retry_action(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    action_id: UUID,
) -> ProviderAction | None:
    row = db.scalar(
        select(ProviderAction).where(
            ProviderAction.tenant_id == tenant_id,
            ProviderAction.id == action_id,
            ProviderAction.deleted_at.is_(None),
        )
    )
    if row is None:
        return None
    if row.status not in {"DEAD_LETTER", "RETRYING", "BLOCKED"}:
        return row
    row.status = "REQUESTED"
    row.next_retry_at = datetime.now(UTC)
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="provider.action.retry",
        entity_type="provider_action",
        entity_id=str(row.id),
        after={"action_type": row.action_type, "provider": row.provider},
        actor_type="human",
    )
    return row


def cancel_action(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    action_id: UUID,
) -> ProviderAction | None:
    row = db.scalar(
        select(ProviderAction).where(
            ProviderAction.tenant_id == tenant_id,
            ProviderAction.id == action_id,
            ProviderAction.deleted_at.is_(None),
        )
    )
    if row is None:
        return None
    row.status = "CANCELLED"
    row.next_retry_at = None
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="provider.action.cancel",
        entity_type="provider_action",
        entity_id=str(row.id),
        after={"action_type": row.action_type},
        actor_type="human",
    )
    return row


def due_uncertain(db: Session, *, limit: int = 50) -> list[ProviderAction]:
    now = datetime.now(UTC)
    return list(
        db.scalars(
            select(ProviderAction)
            .where(
                ProviderAction.deleted_at.is_(None),
                ProviderAction.status == "REQUESTED",
                ProviderAction.updated_at <= now,
            )
            .limit(limit)
        ).all()
    )


def due_retries(db: Session, *, limit: int = 50) -> list[ProviderAction]:
    now = datetime.now(UTC)
    return list(
        db.scalars(
            select(ProviderAction)
            .where(
                ProviderAction.deleted_at.is_(None),
                ProviderAction.status == "RETRYING",
                ProviderAction.next_retry_at.is_not(None),
                ProviderAction.next_retry_at <= now,
            )
            .limit(limit)
        ).all()
    )


def alert_thresholds(raw: str) -> dict[str, int]:
    merged = dict(DEFAULT_ALERTS)
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return merged
    if isinstance(data, dict):
        for key, value in data.items():
            if key in merged:
                try:
                    merged[key] = int(value)
                except (TypeError, ValueError):
                    continue
    return merged
