from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("agrayian", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    beat_schedule={
        "process-outbox": {"task": "process_outbox", "schedule": 60.0},
        "run-autonomous-cycles": {"task": "run_autonomous_cycles", "schedule": 900.0},
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
