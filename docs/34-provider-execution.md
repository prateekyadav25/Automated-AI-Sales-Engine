# Provider execution — Batch 4 gap note

Audit of the Autopilot control plane before live discovery, ads, and voice. Do not duplicate this architecture.

## What already exists

| Seam | Location | Status |
|---|---|---|
| Autopilot cycle | `services/autonomy.py` | Discover → markets → rescore → enroll → queue approvals → post-sale |
| Action dispatch | `services/dispatcher.py` | Function if/else for send, calendar, ads.spend, voice.dial |
| Apify discovery | `providers/lead_discovery.py` | Official REST; search-actor branch when actor id contains `profile-search`; mock invents nobody |
| Ads adapters | `providers/ads.py` | Live LinkedIn/Meta `httpx` when env creds exist; otherwise labeled mock |
| Voice adapters | `providers/voice.py` | Live Twilio/Vapi `httpx`; otherwise labeled mock |
| Gmail/Calendar | `providers/email.py`, `calendar.py` | Per-tenant `provider_accounts`; live never falls back to mock |
| Inbox + webhook | `provider_inbox_events`, `POST /webhooks/{provider}` | Persist then process **in-request**; HMAC only |
| Idempotency | `automation_idempotency_keys` | Used by email send, not ads/voice execution |
| Health | `GET /autonomy/status` | Computed CONNECTED/MOCK/NOT_CONFIGURED; Gmail has timestamps |

## Gaps this batch closes

| Gap | Decision |
|---|---|
| Discovery query is industries + geographies only | Deterministic ICP query builder; harvestapi filters from persisted fields |
| No LinkedIn URL / provider-ref dedupe or provenance columns | Lead provenance + extra dedupe keys |
| Manual discovery bypasses caps | Same budgets on Autopilot and `POST /discovery/run` |
| Unconfigured ads/voice/discovery silently become Mock | Explicit `DISCOVERY_PROVIDER`, `VOICE_PROVIDER`, `*_ADS_MODE`; live + missing creds = NOT_CONFIGURED |
| Ads external id in `notes`; no status/metrics sync | Campaign columns + Celery poll; no invented CTR |
| Budget limits stored, not enforced | Check before every spend action |
| Voice SID in summary; no callbacks/outcomes | `provider_thread_id` + `call_status`; Twilio/Vapi inbox normalize |
| Webhook work in-request | Persist, return 200, process on worker (inline only for SQLite tests) |
| No circuit / dead letter / action trace | `provider_health_states` + `provider_actions` |
| Dispatcher if/else | Handler registry |
| `/metrics` has no business counters | Prometheus labels: provider, action, failure_class |

## Effectively-once

External systems are at-least-once. Business effects are made effectively-once with inbox `(tenant, provider, external_id)` uniqueness, `ads.launch:{tenant}:{approval_id}` / `voice.dial:{tenant}:{approval_id}`, unique provider ids, and state checks (do not relaunch a CONFIRMED campaign).

## Credentials

Apify, LinkedIn Ads, Meta Ads, Twilio, and Vapi stay process-level environment variables. Per-tenant OAuth remains Google-only.

## Out of scope

RLS, pgvector, MinIO, Kubernetes, SSE, trained ML, PagerDuty, WhatsApp send, per-tenant ads/voice OAuth.
