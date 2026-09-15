# 52 — Pilot Readiness Gap Analysis

Audit date: 2026-09-11. Source: repository after Autopilot batches 1–7 (Alembic head `012`). Batch 8 implements the gaps classified below; this file stays the pre-implementation audit.

Classification: **READY** | **PARTIAL** | **BLOCKER** | **OPTIONAL**.

Batch 8 proves the Revenue OS can operate a controlled PILOT tenant, fail safely, recover, explain itself, and collect real outcomes. It does not train production models, weaken ML gates, or invent metrics.

Environment (`ENVIRONMENT`) is not tenant operating mode. Before Batch 8, `tenants` has no `operating_mode`.

## The eight questions

| Question | Before Batch 8 | Class |
|---|---|---|
| Can Autopilot run continuously for days/weeks? | Event + 15m reconcile Beat exists; Beat health gauges unused | PARTIAL |
| Can multiple workers process the same system safely? | Unique keys exist; `claim_key` is check-then-insert; tests are sequential SQLite | BLOCKER |
| Can provider callbacks arrive concurrently without duplicate effects? | Inbox unique `(tenant, provider, external_id)`; no concurrent test | PARTIAL |
| Can external providers fail without breaking the lifecycle? | Circuit + dead letter for ads/voice/discovery; email outside `provider_actions` | PARTIAL |
| Can real lifecycle outcomes be collected correctly? | Won + some labels; no structured lost/churn UI; expansion feedback partial | PARTIAL |
| Can operators understand what the OS is doing? | Autopilot today-counts + entity Automation card; no full journey trace | PARTIAL |
| Can humans intervene safely? | Pause, channel kill, emergency stop, approvals | READY |
| Can we quantify how much manual work the OS removed? | Activities persist; no ROI / touch methodology | BLOCKER |

## Infrastructure and security

| Area | Evidence | Class | Notes |
|---|---|---|---|
| Kubernetes overlays | `infra/kubernetes/base` + staging/production | PARTIAL | Postgres/Redis/object storage not in-cluster |
| Backups | `scripts/backup/backup.sh`, `restore.sh`, `verify_restore.py` | PARTIAL | Operator-run; `backup_success` never set; no CI restore |
| RLS | Alembic `009` FORCE RLS; CI `rls` job on pgvector/pg16 | READY (CI) / PARTIAL (local) | Local pytest skips without `POSTGRES_RLS_ADMIN_URL` |
| Auth / refresh families | Batch 5 | READY | |
| Webhook routing tokens | Batch 5 | READY | No `X-Tenant-Id` |
| SecretProvider / Fernet | Google tokens encrypted | PARTIAL | Ads/voice still process-env |
| Object storage | Local / MinIO / S3 | PARTIAL | Default local disk |
| Malware scan | `knowledge_sources.malware_status` default `NOT_CONFIGURED` | BLOCKER for PRODUCTION files | No scanner protocol or quarantine |
| pgvector retrieve | Batch 5 | READY | IVFFlat/HNSW not installed (correct while chunks are small) |
| OpenAPI drift | CI `--check` | READY | |
| Observability | Prometheus HTTP + provider counters; OTel optional | PARTIAL | `celery_beat_up` / `celery_workers` unused |

## Autopilot and approvals

| Area | Evidence | Class | Notes |
|---|---|---|---|
| Single control plane | `autopilot_settings`, orchestrator, reconcile | READY | |
| Emergency stop | Tenant + `GLOBAL_EMERGENCY_STOP` + channel pauses | READY | |
| Rate limits | Email/contact/gap, discovery caps, ad budgets | PARTIAL | No AI daily budget; no voice dollar budget |
| Quiet hours | Settings + `in_quiet_hours` | READY | |
| Approval TTL | `expires_at` +7 days | PARTIAL | Not tenant-configurable in settings PATCH |
| Approval owners | Entity owners only | PARTIAL | No settings-level owner routing |
| Settings versioning | In-place PATCH + audit | PARTIAL | No version row stamped on later actions |
| Tenant PILOT mode | Missing | BLOCKER | DEMO/PILOT/PRODUCTION not modeled |
| Approval staleness | Unsubscribe cancels pending sends; execute re-checks email/voice consent | PARTIAL | Renewal completed / campaign cancelled not checked at execute |
| Email uncertain send | `EmailMessage` + retry | PARTIAL | Not in `provider_actions` reconcile |

## Providers

| Area | Evidence | Class | Notes |
|---|---|---|---|
| Google email/calendar | Tenant `ProviderAccount` OAuth | READY | History sync; Pub/Sub deferred |
| Discovery / ads / voice | Explicit MOCK/LIVE/NOT_CONFIGURED | PARTIAL | Process-env credentials |
| Provider precedence | Live without creds is NOT_CONFIGURED | PARTIAL | No tenant-account → env-default → NOT_CONFIGURED function |
| WhatsApp | `preferred_channel` enum | BLOCKER for channel completeness | No consent field, provider, or approval path |
| Gmail Pub/Sub | Not implemented | OPTIONAL | Beat history sync + inbox dedupe is enough for pilot scale |
| Zendesk / Freshdesk / ServiceNow / Stripe HTTP | Classes stub `NOT_CONFIGURED` | OPTIONAL | Generic signed webhooks are the production ingest |
| Inbox dedupe | Unique external id | READY | Concurrent proof missing |

## Customer signals and mapping

| Area | Evidence | Class | Notes |
|---|---|---|---|
| Usage / support / finance / ERP webhooks | Signed generic routes | READY | |
| Identity mapping | confirm / ignore / change | PARTIAL | No unlink of confirmed rows; no recalc after correction |
| Health rules-v2 | LIVE+FRESH only | READY | Single-customer rescore exists; no tenant batch rebuild API |
| Feature snapshots | Immutable flag + unique as_of | PARTIAL | `assert_snapshot_immutable` unused on UPDATE/DELETE |

## Learning data (must stay passive)

| Area | Evidence | Class | Notes |
|---|---|---|---|
| Nine prediction tasks | Seeded `DATA_COLLECTION` | READY | Do not weaken gates |
| Readiness API | Full `ReadinessOut` | PARTIAL | UI hides pending / censored / history days |
| Trained models | None | READY | Correct |
| Outcome wiring | Lead converted, opp won | PARTIAL | Lost / churned / renewed / expanded not event-wired with reasons |
| Recommendation feedback | accepted / ignored | PARTIAL | rejected / edited / expired / useful missing |
| Closed-lost reason | `loss_reason` string | PARTIAL | No write API or taxonomy UI |
| Churn reason | Missing | BLOCKER for outcome honesty | |

## Operator surfaces

| Area | Evidence | Class | Notes |
|---|---|---|---|
| Pilot readiness desk | Missing | BLOCKER | |
| Autopilot today counts | `AutonomyTodayOut` | PARTIAL | Not ROI or funnel with honest denominators |
| Entity Automation card | Last/next/blocked | PARTIAL | No View Full Trace |
| Daily / weekly brief | Missing | BLOCKER | |
| Config export | Missing | PARTIAL | Settings GET exists; no secret-free export |
| LLM cost dashboard | `model_usage` write-only | PARTIAL | |

## Concurrency and recovery (pilot proof)

| Area | Evidence | Class | Notes |
|---|---|---|---|
| Unique idempotency keys | `automation_idempotency_keys`, `provider_actions` | PARTIAL | No IntegrityError handler on race |
| Sequential idempotency tests | close-won, double approve, inbox duplicate | READY | Not concurrency |
| Playwright | 15 tests, SQLite, `workers: 1` | PARTIAL | Not concurrency-proof |
| Worker crash after provider call | Heuristic REQUESTED reconcile | BLOCKER | Does not query provider before re-executing |
| Redis loss | Authoritative state in Postgres | PARTIAL | No test that workflows survive broker loss |
| Beat interruption | Status copy is static | BLOCKER | No `scheduler_unhealthy` |

## Intentionally optional / deferred

| Item | Class | Reason |
|---|---|---|
| Gmail Pub/Sub | OPTIONAL | History sync covers pilot volume; Pub/Sub needs Google IAM without measured lag |
| Live Zendesk / Stripe HTTP | OPTIONAL | Generic signed webhooks are valid production |
| HNSW / IVFFlat | OPTIONAL | Chunk counts still small; add after measured latency |
| MLflow | OPTIONAL | Internal Postgres registry |
| PagerDuty | OPTIONAL | Grafana stubs exist |
| 10k-lead CI load | OPTIONAL | Inventing that baseline would be dishonest; measure a small Postgres scenario |

## Batch 8 must close

1. Tenant `operating_mode` + fail-closed PILOT activation.
2. Concurrent idempotency on Postgres (one business effect).
3. Email in `provider_actions`; reconcile-before-retry.
4. WhatsApp architecture as NOT_CONFIGURED (no fake sends).
5. Malware protocol + honest scan states.
6. Structured human outcomes and measurable work.
7. Full trace, briefs, runbooks, measured (not invented) baseline.

Do not train. Demo seed remains DATA_COLLECTION.
