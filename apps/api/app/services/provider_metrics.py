from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "status"])
PROVIDER_DEAD_LETTERS = Counter("provider_dead_letters_total", "Provider dead letters", ["provider"])
CELERY_QUEUE_LENGTH = Gauge("celery_queue_length", "Approximate Celery queue depth")
CELERY_WORKERS = Gauge("celery_workers", "Celery workers reporting")
CELERY_BEAT_UP = Gauge("celery_beat_up", "Celery Beat heartbeat")
BACKUP_SUCCESS = Gauge("backup_success", "Last backup verification succeeded")
APPROVALS_PENDING = Gauge("approvals_pending", "Pending approvals")

PROVIDER_REQUESTS = Counter("provider_requests_total", "Provider requests", ["provider", "action"])
PROVIDER_SUCCESS = Counter("provider_success_total", "Provider successes", ["provider", "action"])
PROVIDER_FAILURES = Counter("provider_failures_total", "Provider failures", ["provider", "action", "failure_class"])
PROVIDER_LATENCY = Histogram("provider_latency_seconds", "Provider latency", ["provider", "action"])
PROVIDER_RATE_LIMITS = Counter("provider_rate_limits_total", "Provider rate limits", ["provider"])
PROVIDER_RETRIES = Counter("provider_retries_total", "Provider retries", ["provider", "action"])
DISCOVERY_CANDIDATES = Counter("discovery_candidates_total", "Discovery candidates", ["provider"])
DISCOVERY_CREATED = Counter("discovery_created_total", "Discovery leads created", ["provider"])
DISCOVERY_DUPLICATES = Counter("discovery_duplicates_total", "Discovery duplicates", ["provider"])
ADS_LAUNCHES = Counter("ads_launches_total", "Ad launches", ["provider"])
ADS_LAUNCH_FAILURES = Counter("ads_launch_failures_total", "Ad launch failures", ["provider"])
VOICE_CALLS = Counter("voice_calls_total", "Voice dials", ["provider"])
VOICE_COMPLETED = Counter("voice_completed_total", "Voice completed", ["provider"])
VOICE_FAILED = Counter("voice_failed_total", "Voice failed", ["provider"])
CUSTOMER_SIGNALS = Counter("customer_signal_ingested_total", "Normalized customer signals", ["provider"])
USAGE_EVENTS = Counter("usage_events_total", "Usage events ingested", ["provider"])
SUPPORT_EVENTS = Counter("support_events_total", "Support events ingested", ["provider"])
FINANCE_EVENTS = Counter("finance_events_total", "Finance events ingested", ["provider"])
HEALTH_RECALCS = Counter("customer_health_recalculations_total", "Customer health recalculations", ["ruleset"])
STALE_DATA = Counter("customer_data_stale_total", "Stale customer intelligence components", ["component"])
DATASET_BUILD_TOTAL = Counter("dataset_build_total", "Dataset builds", ["task_key", "status"])
DATASET_BUILD_FAILURE = Counter("dataset_build_failure", "Dataset build failures", ["task_key"])
TRAINING_JOBS_TOTAL = Counter("training_jobs_total", "Training jobs", ["task_key", "status"])
TRAINING_JOB_FAILURE = Counter("training_job_failure", "Training job failures", ["task_key"])
PREDICTIONS_TOTAL = Counter("predictions_total", "Predictions recorded", ["task_key", "mode"])
SHADOW_PREDICTIONS_TOTAL = Counter("shadow_predictions_total", "Shadow predictions", ["task_key"])
MODEL_EVALUATION_TOTAL = Counter("model_evaluation_total", "Delayed model evaluations", ["task_key"])
SYNC_DURATION = Histogram("integration_sync_duration_seconds", "Integration sync duration", ["provider"])
SYNC_FAILURES = Counter("integration_sync_failures_total", "Integration sync failures", ["provider"])


def observe_request(*, provider: str, action: str, ok: bool, failure_class: str = "", latency_s: float | None = None) -> None:
    safe_provider = (provider or "unknown")[:40]
    safe_action = (action or "unknown")[:40]
    safe_class = (failure_class or "none")[:40]
    PROVIDER_REQUESTS.labels(provider=safe_provider, action=safe_action).inc()
    if ok:
        PROVIDER_SUCCESS.labels(provider=safe_provider, action=safe_action).inc()
    else:
        PROVIDER_FAILURES.labels(provider=safe_provider, action=safe_action, failure_class=safe_class).inc()
        if safe_class == "RATE_LIMIT":
            PROVIDER_RATE_LIMITS.labels(provider=safe_provider).inc()
    if latency_s is not None:
        PROVIDER_LATENCY.labels(provider=safe_provider, action=safe_action).observe(max(latency_s, 0))
