from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("agrayian", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_routes={
        "process_inbox_event": {"queue": "providers"},
        "sync_inbound_mail": {"queue": "providers"},
        "retry_failed_sends": {"queue": "providers"},
        "sync_ad_campaigns": {"queue": "providers"},
        "retry_provider_actions": {"queue": "providers"},
        "reconcile_requested_actions": {"queue": "providers"},
        "ml_evaluate_matured": {"queue": "automation"},
        "ml_build_dataset": {"queue": "automation"},
        "ml_train_candidate": {"queue": "automation"},
        "run_autonomous_cycles": {"queue": "automation"},
        "process_outbox": {"queue": "automation"},
        "post_sale_frequent": {"queue": "automation"},
        "post_sale_daily": {"queue": "automation"},
        "post_sale_weekly": {"queue": "automation"},
    },
    beat_schedule={
        "process-outbox": {"task": "process_outbox", "schedule": 60.0},
        "run-autonomous-cycles": {"task": "run_autonomous_cycles", "schedule": 900.0},
        "sync-inbound-mail": {"task": "sync_inbound_mail", "schedule": 60.0},
        "retry-failed-sends": {"task": "retry_failed_sends", "schedule": 120.0},
        "refresh-integration-tokens": {"task": "refresh_integration_tokens", "schedule": 300.0},
        "post-sale-frequent": {"task": "post_sale_frequent", "schedule": 300.0},
        "post-sale-daily": {"task": "post_sale_daily", "schedule": 86400.0},
        "post-sale-weekly": {"task": "post_sale_weekly", "schedule": 604800.0},
        "process-inbox-backlog": {"task": "process_inbox_backlog", "schedule": 15.0},
        "sync-ad-campaigns": {"task": "sync_ad_campaigns", "schedule": 300.0},
        "retry-provider-actions": {"task": "retry_provider_actions", "schedule": 60.0},
        "reconcile-requested-actions": {"task": "reconcile_requested_actions", "schedule": 120.0},
        "ml-evaluate-matured": {"task": "ml_evaluate_matured", "schedule": 86400.0},
        "scheduler-heartbeat": {"task": "scheduler_heartbeat", "schedule": 60.0},
        "operator-daily-brief": {"task": "operator_daily_brief", "schedule": 86400.0},
    },
)


@celery_app.task(name="run_autonomous_cycles")
def run_autonomous_cycles() -> int:
    from app.services.autonomy import run_autonomous_cycles_for_all_tenants

    return run_autonomous_cycles_for_all_tenants()


@celery_app.task(name="process_outbox")
def process_outbox() -> int:
    from app.db.session import get_engine, get_session
    from app.services.orchestrator import process_pending_events

    get_engine()
    db = get_session()
    try:
        count = process_pending_events(db, limit=200)
        db.commit()
        return count
    finally:
        db.close()


@celery_app.task(name="sync_inbound_mail")
def sync_inbound_mail() -> int:
    from app.services.inbox import sync_all_tenants

    return sync_all_tenants()


@celery_app.task(name="retry_failed_sends")
def retry_failed_sends() -> int:
    from app.db.session import get_engine, get_session
    from app.services.email_send import retry_retrying_sends

    get_engine()
    db = get_session()
    try:
        count = retry_retrying_sends(db)
        db.commit()
        return count
    finally:
        db.close()


@celery_app.task(name="refresh_integration_tokens")
def refresh_integration_tokens() -> int:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.core.config import get_settings as current_settings
    from app.db.session import get_engine, get_session
    from app.models.integrations import ProviderAccount
    from app.services.provider_accounts import refresh_google_token

    get_engine()
    db = get_session()
    try:
        settings = current_settings()
        soon = datetime.now(UTC) + timedelta(minutes=10)
        from app.db.tenant_jobs import run_per_tenant

        def _one(_tenant_id):
            rows = db.scalars(
                select(ProviderAccount).where(
                    ProviderAccount.status == "connected",
                    ProviderAccount.deleted_at.is_(None),
                )
            ).all()
            refreshed = 0
            for row in rows:
                expires = row.token_expires_at
                if expires is not None and expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                if expires is None or expires <= soon:
                    if refresh_google_token(row, client_id=settings.google_client_id, client_secret=settings.google_client_secret):
                        refreshed += 1
            return refreshed

        total = run_per_tenant(db, _one)
        db.commit()
        return total
    finally:
        db.close()


@celery_app.task(name="post_sale_frequent")
def post_sale_frequent() -> int:
    from app.services.post_sale_reconcile import reconcile_all_tenants

    return reconcile_all_tenants("frequent")


@celery_app.task(name="post_sale_daily")
def post_sale_daily() -> int:
    from app.services.post_sale_reconcile import reconcile_all_tenants

    return reconcile_all_tenants("daily")


@celery_app.task(name="post_sale_weekly")
def post_sale_weekly() -> int:
    from app.services.post_sale_reconcile import reconcile_all_tenants

    return reconcile_all_tenants("weekly")


@celery_app.task(name="process_inbox_event")
def process_inbox_event_task(event_id: str, tenant_id: str = "") -> str:
    from uuid import UUID

    from sqlalchemy import select

    from app.db.session import get_engine, get_session
    from app.db.tenant_context import set_tenant_context
    from app.models.identity import User
    from app.models.integrations import ProviderInboxEvent
    from app.services.inbox import process_inbox_event

    get_engine()
    db = get_session()
    try:
        if tenant_id:
            set_tenant_context(db, UUID(tenant_id))
        event = db.get(ProviderInboxEvent, UUID(event_id))
        if event is None:
            return "missing"
        actor = db.scalar(select(User).where(User.tenant_id == event.tenant_id, User.is_active.is_(True)))
        if actor is None:
            return "no_actor"
        status = process_inbox_event(db, event, actor_id=actor.id)
        db.commit()
        return status
    finally:
        db.close()


@celery_app.task(name="process_inbox_backlog")
def process_inbox_backlog() -> int:
    from app.db.session import get_engine, get_session
    from app.db.tenant_jobs import run_per_tenant
    from app.services.inbox import process_pending_inbox

    get_engine()
    db = get_session()
    try:
        count = run_per_tenant(db, lambda _tid: process_pending_inbox(db))
        db.commit()
        return count
    finally:
        db.close()


@celery_app.task(name="sync_ad_campaigns")
def sync_ad_campaigns() -> int:
    from sqlalchemy import select

    from app.db.session import get_engine, get_session
    from app.db.tenant_jobs import run_per_tenant
    from app.models.identity import User
    from app.services.ads import sync_tenant_campaigns

    get_engine()
    db = get_session()
    try:
        def _one(tenant_id):
            user = db.scalar(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)))
            return sync_tenant_campaigns(db, tenant_id=tenant_id, actor_id=user.id if user else None)

        total = run_per_tenant(db, _one)
        db.commit()
        return total
    finally:
        db.close()


@celery_app.task(name="retry_provider_actions")
def retry_provider_actions() -> int:
    from app.db.session import get_engine, get_session
    from app.db.tenant_jobs import run_per_tenant
    from app.models.ai import AIApproval
    from app.services.ads import execute_ads_spend
    from app.services.provider_ops import due_retries
    from app.services.voice import execute_voice_dial

    get_engine()
    db = get_session()
    try:
        def _one(_tenant_id):
            count = 0
            for row in due_retries(db):
                if not row.approval_id:
                    continue
                approval = db.get(AIApproval, row.approval_id)
                if approval is None:
                    continue
                if row.action_type in {"ads.launch", "ads.spend"}:
                    execute_ads_spend(db, tenant_id=row.tenant_id, actor_id=row.created_by or approval.created_by, approval=approval)
                    count += 1
                elif row.action_type == "voice.dial":
                    execute_voice_dial(db, tenant_id=row.tenant_id, actor_id=row.created_by or approval.created_by, approval=approval)
                    count += 1
            return count

        total = run_per_tenant(db, _one)
        db.commit()
        return total
    finally:
        db.close()


@celery_app.task(name="ml_evaluate_matured")
def ml_evaluate_matured() -> int:
    from app.db.session import get_engine, get_session
    from app.db.tenant_jobs import run_per_tenant
    from app.services.ml.evaluate import evaluate_matured

    get_engine()
    db = get_session()
    try:

        def _one(tenant_id):
            return evaluate_matured(db, tenant_id=tenant_id)

        total = run_per_tenant(db, _one)
        db.commit()
        return total
    finally:
        db.close()


@celery_app.task(name="ml_build_dataset")
def ml_build_dataset_task(tenant_id: str, task_key: str) -> str:
    from uuid import UUID

    from app.db.session import get_engine, get_session
    from app.db.tenant_context import set_tenant_context
    from app.services.ml.dataset import build_dataset
    from app.services.ml.readiness import assert_ready_for_experiment

    get_engine()
    db = get_session()
    try:
        tid = UUID(tenant_id)
        set_tenant_context(db, tid)
        assert_ready_for_experiment(db, tenant_id=tid, task_key=task_key)
        row = build_dataset(db, tenant_id=tid, actor_id=None, task_key=task_key)
        db.commit()
        return row.version
    finally:
        db.close()


@celery_app.task(name="ml_train_candidate")
def ml_train_candidate_task(tenant_id: str, task_key: str, dataset_version: str) -> str:
    from uuid import UUID

    from app.db.session import get_engine, get_session
    from app.db.tenant_context import set_tenant_context
    from app.services.ml.train import train_candidate

    get_engine()
    db = get_session()
    try:
        tid = UUID(tenant_id)
        set_tenant_context(db, tid)
        row = train_candidate(db, tenant_id=tid, actor_id=None, task_key=task_key, dataset_version=dataset_version)
        db.commit()
        return row.version
    finally:
        db.close()


@celery_app.task(name="scheduler_heartbeat")
def scheduler_heartbeat() -> str:
    from app.db.session import get_engine, get_session
    from app.services.scheduler_health import record_beat, record_worker

    get_engine()
    db = get_session()
    try:
        record_beat(db)
        record_worker(1)
        db.commit()
        return "ok"
    finally:
        db.close()


@celery_app.task(name="operator_daily_brief")
def operator_daily_brief() -> int:
    from app.db.session import get_engine, get_session
    from app.db.tenant_jobs import run_per_tenant
    from app.services.operator_briefs import generate_brief

    get_engine()
    db = get_session()
    try:
        def _one(tenant_id):
            generate_brief(db, tenant_id=tenant_id, actor_id=None, kind="daily")
            return 1

        total = run_per_tenant(db, _one)
        db.commit()
        return total
    finally:
        db.close()


@celery_app.task(name="reconcile_requested_actions")
def reconcile_requested_actions() -> int:
    from datetime import UTC, datetime, timedelta

    from app.db.session import get_engine, get_session
    from app.db.tenant_jobs import run_per_tenant
    from app.services.provider_ops import due_uncertain

    get_engine()
    db = get_session()
    try:
        cutoff = datetime.now(UTC) - timedelta(minutes=5)

        def _one(_tenant_id):
            count = 0
            for row in due_uncertain(db):
                updated = row.updated_at
                if updated is not None and updated.tzinfo is None:
                    updated = updated.replace(tzinfo=UTC)
                if updated is not None and updated > cutoff:
                    continue
                if row.external_id:
                    row.status = "CONFIRMED"
                else:
                    row.status = "RETRYING"
                    row.next_retry_at = datetime.now(UTC)
                count += 1
            return count

        total = run_per_tenant(db, _one)
        db.commit()
        return total
    finally:
        db.close()
