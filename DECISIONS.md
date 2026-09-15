# Decisions

## ADR-001 — Monorepo shape

Next.js web, FastAPI API, Celery worker, shared TS packages, `ai/` and `ml/` trees.

Trade-off: two runtimes in one repo. Accepted because the product is one system and the spec requires this split.

## ADR-002 — Shared schema multi-tenancy

Every tenant-owned row has `tenant_id`. Repositories filter. RLS is planned hardening, not MVP.

Trade-off: application-level isolation requires discipline and tests. Faster to ship than database-per-tenant.

## ADR-003 — Session model

Argon2 hashes, JWT access tokens, rotating refresh cookies.

## ADR-004 — LLM data path

LLM → approved tool → application service → authorization → repository → database. No raw SQL tools.

## ADR-005 — Provider interfaces

OpenAI + Mock for LLM and embeddings. Mock is labeled and used when no key is configured.

## ADR-006 — Post-sale stubs

Closed Won creates `customers` and `renewals` so CS/renewal modules can attach later.

## ADR-007 — Deterministic math

Scores, KPIs, discounts, and revenue figures are computed in code. LLMs explain them.

## ADR-008 — Feature flags

Unfinished engines are flagged. UI may show coming-soon empty states. No fabricated metrics.

## ADR-009 — Embeddings storage

MVP stores embedding vectors as JSON lists so SQLite tests and PostgreSQL both work. pgvector indexes are a later optimization when Postgres-only retrieval is required.

## ADR-010 — Autopilot control plane

Reuse `autonomous_runs`, `domain_events`, and `AIApproval`. Do not add a second job table or revive unused `WorkflowDefinition`.

`lead.status` stays the business lifecycle. Automation progress lives in `entity_automation_states`. `ENABLE_AUTOPILOT` remains a coarse flag; `autopilot_settings.enabled` is the operating source of truth and upserts the flag.

Orchestrator consumes the outbox and calls domain services. LLMs do not invent scores, qualification, or revenue. Email in batch 1 is MockEmailProvider only. UI polls; no SSE.

## ADR-011 — Live engagement loop

One Google `provider_accounts` row per tenant user holds Gmail and Calendar scopes. Tokens are Fernet-encrypted (`TOKEN_ENCRYPTION_KEY` or derived from `SECRET_KEY`). APIs never return tokens.

`Conversation` is the thread. Child `email_messages` carry provider ids and send status. `ActionDispatcher` executes approvals. Send idempotency is `email.send:{tenant}:{approval_id}`. Live mode without a connection is `BLOCKED BY CONFIGURATION`, not a mock send.

Inbound starts as scheduled Gmail history sync plus durable `provider_inbox_events`. ReplyIntelligence returns structured JSON with the inbound body wrapped as untrusted and no tools. A deterministic router owns unsubscribe, nurture, reply drafts, and meeting proposals. Slot math is computed in code against busy times.

SSE stays deferred. UI still polls.

## ADR-012 — Post-sale revenue autopilot

Reuse the Autopilot control plane. Do not add a second automation engine.

`Customer.lifecycle_state` is business state. Automation stays in `entity_automation_states` with `entity_type="customer"`.

Closed Won mints a minimal `Contract` + `ContractLine` from the won Quote, falling back to `Opportunity.amount`. Unknown term and escalation stay `null`.

Health is `rules-v1`. MOCK usage and UNAVAILABLE support/finance are excluded from the numeric total. LLMs explain; they do not invent ARR, ROI, NRR, usage, or quotes.

Renewal windows are 180/120/90/60/30 with idempotency key `renewal.window:{tenant}:{renewal}:{days}`. Commercial baseline is deterministic from the contract.

Expansion Autopilot writes `ExpansionRecommendation` only. `expansion_auto_opportunity_enabled` defaults false. Minting a CRM Opportunity needs `expansion.opportunity.create` approval.

Advocacy uses `advocacy-rules-v1`. Not every healthy customer is eligible. `quote` stays null until a human approves. Referrals re-enter acquisition with `source=referral` and no implied consent.

Human approval remains mandatory for discount ≥10%, pricing change, renewal commercial, expansion commercial, and contract modification.

UI polls every 5s. SSE stays deferred.

## ADR-013 — Live channel execution and process-level credentials

Reuse the Autopilot path: Workflow → Approval → ActionDispatcher → Provider → callback/poll → `provider_inbox_events` → domain event. Do not add a second job engine.

Apify, LinkedIn Ads, Meta Ads, Twilio, and Vapi stay process-level environment variables. Per-tenant OAuth remains Google-only.

Explicit modes default to mock for CI. Live mode + missing credentials is `NOT_CONFIGURED`. Live HTTP failure is `ERROR` / `RATE_LIMITED` / `DEGRADED`. Never silently swap LIVE → MOCK.

Mark launched / dialed / discovered only after persist-then-confirm (`provider_actions` REQUESTED → CONFIRMED with a provider id or success body).

External platforms are at-least-once. Effectively-once business effects use inbox `(tenant, provider, external_id)` uniqueness, `ads.launch:{tenant}:{approval_id}` / `voice.dial:{tenant}:{approval_id}`, unique provider ids, and state checks.

WhatsApp is a preference enum only. No WhatsApp provider in this batch.

## ADR-014 — RLS tenant context

Shared schema stays. Application `tenant_id` filters stay mandatory. Postgres RLS is defense-in-depth.

`SELECT set_config(:key, :value, true)` is the only session write. Tenant IDs are never interpolated into SQL. Roles: `agrayian_app` (no `BYPASSRLS`), `agrayian_migrator` and `agrayian_admin` (bypass). SQLite no-ops the context helper.

## ADR-015 — Refresh-token families

Refresh cookies rotate. Reuse of a rotated hash revokes the whole family and audits `auth.refresh_reuse_detected`. Raw tokens are never stored.

## ADR-016 — pgvector expand / migrate / contract

`knowledge_chunks.embedding` is `vector(N)` from `EMBEDDING_DIMENSIONS`. Retrieval uses cosine (`<=>`) with a tenant filter. `embedding_json` remains until Postgres retrieval is proven. No IVFFlat/HNSW while chunk counts are small.

## ADR-017 — Object storage

Domain services use `ObjectStorageProvider`. Keys are `tenant/{tenant_id}/knowledge/{document_id}/{version}/source`. Postgres keeps metadata and extracted text. Original bytes live in local disk, MinIO, or S3. Malware scan is `NOT_CONFIGURED` until a scanner is wired.

## ADR-018 — SSE is UI-only

`GET /api/v1/autonomy/events` streams status. Authoritative state stays Postgres. The web client keeps 5s polling as fallback.

## ADR-019 — Kubernetes topology

Kustomize deploys `web`, `api`, `worker`, and `beat` (Beat replicas=1). Migrations run as a Job with the admin DSN. API replicas do not migrate or seed.

## ADR-020 — Backup and restore

`scripts/backup` dumps Postgres with the admin role. Object storage is operator-mirrored. Restore is proven with `verify_restore.py` against a temporary database.

## ADR-021 — Generic webhooks, not vendor lock-in

Usage, support, finance, and ERP enter through the existing signed webhook route. Body `tenant_id` is never trusted. Customer identity uses `external_entity_mappings`. Vendor HTTP (Zendesk, Stripe, …) stays stubbed as `NOT_CONFIGURED`.

## ADR-022 — One live health row, rules-v2

`HealthScore` stays one row per customer. The active ruleset is `rules-v2`. Snapshots keep `ruleset_version`. Trend and `customer.health_changed` compare only same-version snapshots. Only LIVE + fresh components enter the denominator. `health_data_coverage` is persisted and shown separately. STALE is not scored as zero usage.

## ADR-023 — Point-in-time features

A training or prediction row at time T may only use data observed at or before T. Feature snapshots are immutable and keyed by `as_of`. Dataset builds fail if a feature's `max_observed_at` is after `as_of`.

## ADR-024 — Dataset versioning and fingerprints

Datasets are tenant-local, versioned, and fingerprinted. Same inputs must produce the same hash. Splits are temporal. Cross-tenant pooling is rejected.

## ADR-025 — Tenant model isolation

ML tables carry `tenant_id` and FORCE RLS. Insufficient tenant data stays rules-based. Shared or federated models need a separate legal design.

## ADR-026 — Champion / challenger

Rules-v1 / rules-v2 are CHAMPION. Future ML starts as EXPERIMENTAL or CHALLENGER. Promotion is a governed admin action. Batch 7 refuses ML CHAMPION.

## ADR-027 — Shadow inference

A challenger may write `Prediction` rows with `execution_mode=SHADOW`. Autopilot and provider execution never read them. `ACTIVE` is rejected for non-rules providers.

## ADR-028 — Model artifact storage

Artifacts live in `ObjectStorageProvider` under `tenant/{id}/models/{task}/{version}/`. Postgres holds metadata only. Download requires `ml.train`.

## ADR-029 — Tenant operating mode vs environment

`ENVIRONMENT` is deployment (`development|test|staging|production`). `tenants.operating_mode` is `DEMO|PILOT|PRODUCTION`. Demo seed stays DEMO. Changing mode goes through `PilotReadinessService.activate()` and fails closed on critical checks.

## ADR-030 — Provider precedence

Resolve credentials as tenant `ProviderAccount` → deployment default only if `allow_deployment_provider_defaults` → `NOT_CONFIGURED`. Never LIVE → MOCK.

## ADR-031 — Concurrent idempotency

Claim unique keys inside a nested transaction. On unique violation, return the existing effect. Postgres `SELECT … FOR UPDATE` locks the opportunity before close-won. After an uncertain provider call, reconcile remote state before re-executing.

## ADR-032 — WhatsApp consent isolation

`consent_whatsapp` is never inferred from email or voice. Sends require an approved template, an approval, and a configured provider. The default adapter is `NOT_CONFIGURED`.

## ADR-033 — Malware and quarantine honesty

Uploads are quarantined, then scanned. Status is honest (`SCANNED_CLEAN|SCANNED_BLOCKED|NOT_SCANNED|NOT_CONFIGURED`). PILOT may allow unscanned files. PRODUCTION blocks when the scanner is unavailable.

## ADR-034 — Automation ROI definition

ROI uses persisted activities, approvals, and overrides. Autonomous Execution Rate is system-executed / eligible. Revenue associated with AI-prepared opportunities uses provenance. Never “AI generated ₹X” or employee replacement.

## ADR-035 — Gmail Pub/Sub deferred

Pilot scale is covered by Beat history sync plus inbox dedupe. Pub/Sub adds Google project/IAM complexity without a measured ingest lag. Revisit after a measured lag.

## ADR-036 — Tenant credentials win execution

`resolve_channel` plus provider factories accept the tenant `ProviderAccount` row. A connected tenant credential is LIVE even when deployment mode is mock. Live without credentials is `NOT_CONFIGURED`. There is no silent LIVE→MOCK fallback.

## ADR-037 — Split voice + honest Exotel callbacks

Telephony and conversation are independent. `+91` routes to Exotel unless the tenant overrides. Exotel does not HMAC-sign status callbacks; ingest trusts the routing token and an optional IP allowlist. NDNC/DND, TRAI hours, and recording consent are hard India pre-dial gates.

## ADR-038 — First-touch paid attribution

`campaign_id`, ad identifiers, and UTM values copy from inbound capture onto Lead and Opportunity. Campaign ROAS is closed-won amount on that `campaign_id` divided by persisted `campaign.spent`. LLMs do not invent either number.
