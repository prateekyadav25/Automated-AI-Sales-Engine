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
