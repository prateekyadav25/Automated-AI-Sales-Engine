import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.identity import Tenant
from app.models.integrations import ProviderAction
from app.models.pilot import SchedulerHeartbeat
from app.services.provider_ops import begin_action, classify_http, confirm_action, fail_action
from app.services.scheduler_health import beat_status, record_beat

pytestmark = pytest.mark.postgres


def _url() -> str | None:
    return os.environ.get("POSTGRES_CONCURRENCY_URL") or os.environ.get("POSTGRES_RLS_ADMIN_URL")


@pytest.fixture(scope="module")
def pg() -> sessionmaker:
    url = _url()
    if not url:
        pytest.skip("POSTGRES_RLS_ADMIN_URL is not set")
    engine = create_engine(url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_provider_errors_do_not_become_mock() -> None:
    assert classify_http(429) == "RATE_LIMIT"
    assert classify_http(500) == "TRANSIENT"
    assert classify_http(0, timeout=True) == "TRANSIENT"
    assert classify_http(401) == "AUTHENTICATION"


def test_beat_stale_marks_scheduler_unhealthy(pg: sessionmaker) -> None:
    db = pg()
    try:
        record_beat(db)
        db.commit()
        ok = beat_status(db, stale_after=timedelta(minutes=20))
        assert ok["scheduler_unhealthy"] is False
        row = db.get(SchedulerHeartbeat, "celery_beat")
        assert row is not None
        row.last_beat_at = datetime.now(UTC) - timedelta(hours=2)
        db.commit()
        stale = beat_status(db, stale_after=timedelta(minutes=20))
        assert stale["scheduler_unhealthy"] is True
    finally:
        db.close()


def test_postgres_authoritative_without_redis(pg: sessionmaker) -> None:
    db = pg()
    try:
        tenant = db.scalar(select(Tenant))
        assert tenant is not None
        assert tenant.id
        slug = tenant.slug
        db.expunge_all()
        again = db.scalar(select(Tenant).where(Tenant.slug == slug))
        assert again is not None
        assert again.id == tenant.id
    finally:
        db.close()


def test_uncertain_action_reconciles_without_second_row(pg: sessionmaker) -> None:
    db = pg()
    try:
        tenant = db.scalar(select(Tenant))
        assert tenant is not None
        key = f"email.send:{tenant.id}:{uuid4()}"
        first = begin_action(
            db,
            tenant_id=tenant.id,
            actor_id=None,
            action_type="email.send",
            idempotency_key=key,
            provider="mock-email",
        )
        confirm_action(first, provider="mock-email", external_id="ext-1", response_summary="sent")
        db.flush()
        second = begin_action(
            db,
            tenant_id=tenant.id,
            actor_id=None,
            action_type="email.send",
            idempotency_key=key,
            provider="mock-email",
        )
        assert second.id == first.id
        assert second.status == "CONFIRMED"
        assert second.external_id == "ext-1"
        db.commit()
    finally:
        db.close()


def test_provider_failure_dead_letters(pg: sessionmaker) -> None:
    db = pg()
    try:
        tenant = db.scalar(select(Tenant))
        assert tenant is not None
        row = begin_action(
            db,
            tenant_id=tenant.id,
            actor_id=None,
            action_type="email.send",
            idempotency_key=f"fail:{uuid4()}",
            provider="mock-email",
        )
        fail_action(row, failure_class="PERMANENT", error="500 from provider", retryable=False)
        db.flush()
        stored = db.get(ProviderAction, row.id)
        assert stored is not None
        assert stored.status == "DEAD_LETTER"
        assert stored.failure_class == "PERMANENT"
        db.commit()
    finally:
        db.close()
