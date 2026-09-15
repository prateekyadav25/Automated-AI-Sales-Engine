# 35 — Production Readiness Gap Analysis

Batch 5 audit of the AGRAYIAN Autonomous Revenue OS repository as of Autopilot batches 1–4. Classifications:

- **DONE** — implemented and verified in code
- **PARTIAL** — exists but incomplete for enterprise production
- **MISSING** — not implemented
- **BLOCKER** — must be resolved before production go-live
- **DEFERRED** — intentionally out of Batch 5 or later work

Evidence refers to the repository at audit time, before Batch 5 implementation.

| # | Item | Status | Evidence / notes |
|---|---|---|---|
| 1 | Postgres RLS | **BLOCKER** | Shared schema + `tenant_id` + `get_owned` only. No RLS in Alembic 001–008. ADR-002 planned it. |
| 2 | RLS tenant context | **MISSING** | `session.py` has no `set_config`. Celery tasks query without session tenant vars. |
| 3 | RLS bypass roles | **MISSING** | Compose uses a single Postgres superuser (`agrayian`). No `agrayian_app` / migrator / admin split. |
| 4 | RLS tests | **MISSING** | Isolation tests are SQLite (`conftest.py`). No omit-predicate regression. |
| 5 | pgvector | **MISSING** | `KnowledgeChunk.embedding_json` Text. Image `pgvector/pg16` unused. ADR-009. |
| 6 | Safe vector migration | **MISSING** | No expand/migrate/contract path. |
| 7 | Vector indexing | **MISSING** | In-memory cosine over all tenant chunks (`rag.py`). |
| 8 | RAG retrieval isolation | **PARTIAL** | Application `tenant_id` filter + source re-check. No RLS. Abstain is prompt-only. |
| 9 | MinIO/S3 cutover | **MISSING** | Compose MinIO + S3 env only. Upload decodes UTF-8 and discards bytes. |
| 10 | ObjectStorageProvider | **MISSING** | No boto/minio abstraction in app code. |
| 11 | Tenant-scoped object keys | **MISSING** | No object keys. |
| 12 | Secure downloads | **MISSING** | No binary download endpoint. |
| 13 | File security | **PARTIAL** | 1MB size cap. No MIME/type allowlist, malware hook, or archive handling. |
| 14 | Refresh token family | **BLOCKER** | `RefreshToken` has hash/expiry/revoked only. No family/jti/replaced_by/reuse. |
| 15 | Token reuse response | **MISSING** | Reuse of rotated token returns 401 only. No family revoke or `auth.refresh_reuse_detected`. |
| 16 | Session management | **MISSING** | Logout revokes current cookie only. No list/revoke/revoke-all. |
| 17 | OpenAPI generated types | **MISSING** | FastAPI OpenAPI exists. Web uses handwritten `apps/web/src/lib/types.ts`. `packages/types` has Envelope/TokenUser only. |
| 18 | OpenAPI CI drift | **MISSING** | No generate script or drift job. |
| 19 | SecretProvider | **MISSING** | Pydantic Settings / `.env` only. |
| 20 | Secret classification | **PARTIAL** | Tokens stripped from integration APIs. No formal classification or leak tests. |
| 21 | Fernet key management | **PARTIAL** | Fernet via `TOKEN_ENCRYPTION_KEY` or SHA256(`SECRET_KEY`). No versioning/rotation docs. |
| 22 | Backup / restore | **BLOCKER** | No scripts. Compose volumes only. |
| 23 | Restore test | **MISSING** | Never restored. |
| 24 | DR runbook | **MISSING** | No `docs/36-disaster-recovery.md`. |
| 25 | Redis failure behavior | **PARTIAL** | Redis is Celery broker. No documented fallback. Business state is Postgres. |
| 26 | Celery delivery safety | **PARTIAL** | Domain idempotency keys exist. No `acks_late`. No task-level retry config. |
| 27 | Dead-letter operations | **PARTIAL** | APIs + Autopilot panel retry/cancel. Thin inspect, no pagination. |
| 28 | Workflow recovery | **PARTIAL** | Run steps persisted. No operator resume that checks external confirmation. |
| 29 | Provider reconciliation | **MISSING** | `REQUESTED` never swept. Only `RETRYING` retried. |
| 30 | Database constraint audit | **PARTIAL** | Strong uniques on provider inbox/actions/idempotency. Missing customer/opportunity, renewal/customer, approval key unique. |
| 31 | Transaction boundaries | **PARTIAL** | Most services commit at API. Need audit of Closed Won / activation / approval execute. |
| 32 | Concurrency control | **PARTIAL** | `claim_key` + unique idempotency. No row locks on close-won/activation. |
| 33 | Authorization audit | **PARTIAL** | Most routes use `require_permission`. `/metrics` open. Webhooks unauthenticated by design. |
| 34 | AI tool authorization | **DONE** | LLM → approved tool → `get_owned` / tenant filter. No raw SQL tools. |
| 35 | Prompt injection boundaries | **PARTIAL** | Reply intelligence wraps inbound as untrusted. No dedicated injection tests for docs/web/email. |
| 36 | Webhook security | **BLOCKER** | HMAC/Twilio/Vapi verified. Tenant from `X-Tenant-Id`. No body size cap. |
| 37 | Rate limiting | **MISSING** | Docs claim it. No HTTP limiter. |
| 38 | API request limits | **PARTIAL** | Knowledge 1MB, CSV 500KB. No global body/pagination/AI input caps. |
| 39 | CSV security | **PARTIAL** | 200-row cap. No formula-injection hardening on export. |
| 40 | Audit log immutability | **DONE** | Append-only `write_audit`. Admin list is read-only. |
| 41 | Audit event coverage | **PARTIAL** | Login audited. Refresh/logout/failed auth not. Some mutations emit events only. |
| 42 | PII / sensitive logging | **PARTIAL** | JSON logs + provider `redact()`. No global token/header/email filter. |
| 43 | Data retention architecture | **MISSING** | No tenant retention policies. |
| 44 | Data export / delete foundation | **MISSING** | No privacy export/delete. Suppression must survive later. |
| 45 | Health endpoints | **PARTIAL** | `/health` liveness-ish, `/ready` hits Postgres. Paths are not `/health/live` and `/health/ready`. |
| 46 | Dependency health | **PARTIAL** | Ready checks DB only. Redis/migrations/providers not classified. |
| 47 | Migration safety | **PARTIAL** | 001 is `create_all`. Later revs additive. No expand/contract rules doc. |
| 48 | Startup migration behavior | **BLOCKER** | Compose API runs `alembic upgrade head && python -m app.seed` on every replica start. |
| 49 | DB connection management | **PARTIAL** | Engine defaults. No pool/recycle/timeout config. |
| 50 | Query performance | **PARTIAL** | Some indexes via mixin. Home/Autopilot still scan-ish. No EXPLAIN baselines. |
| 51 | Pagination | **PARTIAL** | CRM lists paginate. Activities, runs, approvals unpaginated. Audit `limit(100)`. Actions `limit=50`. |
| 52 | SSE | **MISSING** | TanStack `refetchInterval: 5000` everywhere. ADR deferred SSE. |
| 53 | SSE reconnect | **MISSING** | — |
| 54 | Polling fallback | **DONE** | 5s polling is the current authority path. Keep after SSE. |
| 55 | OpenTelemetry | **MISSING** | Correlation IDs only. No OTel SDK. |
| 56 | Prometheus | **PARTIAL** | `/metrics` + provider counters. Missing HTTP/DB/queue/Autopilot/DLQ series. Unauthenticated. |
| 57 | Grafana | **MISSING** | No versioned dashboards. |
| 58 | Alert rules | **PARTIAL** | In-app `alert_rules_json` on Autopilot. No Prometheus/Alertmanager rules. |
| 59 | Celery Beat singleton | **PARTIAL** | Separate compose `beat` service. Replicas=1 locally. No leader election. |
| 60 | Worker queue separation | **MISSING** | Default queue only. |
| 61 | AI timeouts / budgets | **PARTIAL** | Usage rows exist. No hard timeout/retry/cost budget on every call. |
| 62 | AI failure behavior | **PARTIAL** | Scoring is deterministic. External AI drafts degrade ad hoc. |
| 63 | Model configuration | **DONE** | Model names from settings. Empty → mock. |
| 64 | Frontend error boundaries | **PARTIAL** | Pages have loading/empty/error in many desks. Session expiry/SSE not covered. |
| 65 | Accessibility | **PARTIAL** | Semantic-ish app shell. No systematic a11y audit. |
| 66 | Security headers | **PARTIAL** | nosniff, DENY, Referrer-Policy, Permissions-Policy. No CSP/HSTS. |
| 67 | CORS | **DONE** | Allowlist + credentials. No wildcard. |
| 68 | Cookie security | **PARTIAL** | HttpOnly, SameSite=lax, path scoped, Secure via flag (default false). `cookie_domain` unused. |
| 69 | Password security | **DONE** | Argon2 defaults. Do not weaken. |
| 70 | Account protection | **MISSING** | Failed login 401 same message. No throttle. No failed-auth audit. |
| 71 | Admin protection | **PARTIAL** | Permission strings on admin routes. No step-up for kill/flags/disconnect. |
| 72 | Dependency security | **MISSING** | CI has no pip-audit / npm audit / image scan. Aikido optional unsigned. |
| 73 | Secret scanning | **MISSING** | No gitleaks/trufflehog in CI. |
| 74 | SAST | **MISSING** | No Bandit/ruff-security baseline. Aikido = NOT_CONFIGURED. |
| 75 | Container hardening | **PARTIAL** | Slim/alpine images. Run as root. No healthcheck in Dockerfiles. |
| 76 | Production Docker image | **PARTIAL** | API uvicorn, web `pnpm start`. Compose also migrates+seeds. |
| 77 | Kubernetes | **MISSING** | `infra/kubernetes/README.md` stub. |
| 78 | K8s configuration | **MISSING** | — |
| 79 | K8s workers | **MISSING** | Compose separates api/worker/beat. No K8s Deployments. |
| 80 | Horizontal scaling | **PARTIAL** | API/web are stateless. Undocumented. |
| 81 | Deployment environments | **PARTIAL** | `environment` setting exists. Behavior still scattered. |
| 82 | Staging | **MISSING** | No staging overlay or live-outreach guard. |
| 83 | Environment safety | **MISSING** | Compose interpolates host `.env` including live provider tokens. |
| 84 | Database environment safety | **BLOCKER** | Seed has no production refuse. `seed_demo` default true and unused. |
| 85 | Demo account | **BLOCKER** | `admin@agrayian.demo` / `Agrarian!Demo1` always seedable. |
| 86 | Seed safety | **BLOCKER** | Compose always `python -m app.seed`. |
| 87 | Timezones | **PARTIAL** | Timestamps UTC. Quiet hours use tenant timezone string. DST tests thin. |
| 88 | Clock / date tests | **PARTIAL** | Quiet hours flake history. No midnight/DST suite. |
| 89 | Commercial calculations | **PARTIAL** | Decimal math in CPQ/renewal. Need regression pack. |
| 90 | Money database types | **DONE** | `Numeric(18,2)` / Decimal. No Float columns. |
| 91 | Currency | **PARTIAL** | Amounts stored without explicit currency on all aggregates. |
| 92 | Load testing | **MISSING** | No repeatable harness. |
| 93 | Autopilot scale test | **MISSING** | Reconcile loops tenants; not proven bounded. |
| 94 | Reconciliation watermarks | **PARTIAL** | Idempotency keys + due retries. Some full-table scans remain. |
| 95 | Version compatibility | **PARTIAL** | Additive migrations. No worker/API dual-version contract. |
| 96 | Domain event versioning | **MISSING** | `DomainEvent.event_type` string only. No `schema_version`. |
| 97 | Webhook payload versioning | **PARTIAL** | Inbox stores raw JSON. Domain handlers parse provider fields directly. |
| 98 | Incident operations | **MISSING** | No `docs/37-incident-response.md`. |
| 99 | Emergency Autopilot kill | **PARTIAL** | `autopilot_settings.enabled` + entity pause. No emergency “stop new external actions” that preserves work. |
| 100 | Channel kill switches | **PARTIAL** | Many feature booleans. Email/ads/voice/discovery not named as emergency channel pauses. |
| 101 | Autopilot safety limits | **PARTIAL** | Daily email/discovery/budget limits exist. Missing high-risk fail-closed if unset in prod. |
| 102 | Approval expiry | **MISSING** | No `expires_at` on `AIApproval`. |
| 103 | Stale action invalidation | **PARTIAL** | Email re-checks consent. Voice execute checks `opt_out` only. No unsubscribe/renewed/cancelled invalidation. |
| 104 | Approval age observability | **MISSING** | No pending/oldest/turnaround metrics. |
| 105 | Performance budgets | **MISSING** | No recorded p95 targets/baselines. |
| 106 | Production readiness checklist | **MISSING** | No `docs/38-production-readiness-checklist.md`. |
| 107 | Go-live blockers list | **MISSING** | This document starts it; checklist must track evidence after implementation. |
| 108 | CI pipeline | **PARTIAL** | ruff, pytest (SQLite), lint/tsc/vitest/build, Playwright. Missing security/RLS/OpenAPI/alembic/container. |
| 109 | Migration CI | **MISSING** | E2E seeds SQLite, does not `alembic upgrade`. |
| 110 | Test database RLS | **BLOCKER** | SQLite cannot prove RLS. |
| 111 | Test provider safety | **PARTIAL** | Defaults mock. CI e2e does not force all provider modes to mock if `.env` leaks. |
| 112 | Playwright expansion | **PARTIAL** | 10 journeys. Missing pause/resume, DLQ inspect, session expiry, knowledge after storage cutover. |
| 113 | Honest mocks | **DONE** | MOCK / UNAVAILABLE / NOT_CONFIGURED labels in Batch 4. Must preserve. |
| 114 | Operations documentation | **PARTIAL** | Architecture docs 00–34. Missing backup/restore/rollback/kill/Fernet rotation runbooks. |
| 115 | No advanced ML | **DONE** | Model cards `rules-v1`, `last_trained` null. Keep. |
| 116 | No more feature desks | **DONE** | Batch 5 must not add nav groups. |
| 117 | Implementation order | **DONE** | Locked: 5A → 5B → 5C → 5D. |
| 118 | Validate after each sub-batch | **PARTIAL** | Process defined. Not yet executed for Batch 5. |
| 119 | Status documents / ADRs | **PARTIAL** | Status files current through Batch 4. Batch 5 ADRs not written. |
| 120 | Definition of Batch 5 complete | **MISSING** | 18 criteria unverified until implementation. |

## P0 go-live blockers (pre-Batch 5)

1. No PostgreSQL RLS / non-superuser app role.
2. Refresh-token replay does not revoke the family.
3. Webhook tenant taken from client header.
4. Demo seed and known password can run in production.
5. Compose applies migrations and seeds on every API start.
6. No backup that has been restored.
7. CI cannot prove RLS (SQLite only).
8. Live provider credentials can leak into CI via host `.env`.

## Honest mocks (must remain)

`MOCK`, `UNAVAILABLE`, and `NOT_CONFIGURED` stay labels. Aikido = **NOT_CONFIGURED** unless signed in. Production hardening must not invent success for missing scanners, malware engines, or SaaS providers.

## Batch 5 closeout

The classifications above are the pre-implementation audit. Batch 5 implemented 5A–5D against that list. Residual debt is in `TECHNICAL_DEBT.md`. PagerDuty, per-tenant ads/voice OAuth, WhatsApp send, trained ML, Gmail Pub/Sub, and Aikido-as-required stay **DEFERRED**.
