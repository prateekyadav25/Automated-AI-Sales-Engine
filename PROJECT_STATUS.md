# Project Status Overview

## CURRENT PHASE

2026-11-06: Milestone 048 is on branch `social-growth-047-hardening`. Isolated staging is running Alembic `048`. The demonstration is still Alembic `046` and was not migrated or restarted. Live publishing, insights, and GA4 stay off. `/growth/acceptance` is the authorization workflow. Doc 64 is the release report. A public HTTPS host, Meta app credentials, and a Page token are still required before any live check. Paid activation and reporting, and SEO, remain open. The sales engine is not finished.

Earlier on 2026-10-28: purchase onboarding, evidence-backed health, and reviewable retention follow-through reached the local application at Alembic `045`. The paragraph below is the older phase inventory.

Phases 0–22 plus Autopilot batches 1–8 and the full-funnel completion slice are in product. Tenant credentials now drive ads, voice, and discovery execution. Voice is split into telephony and conversation with Exotel as India primary. Meeting capture and transcript-only intelligence exist. Ads persist CTR/CPC/CPL and can pause/sync. Public inbound capture and first-touch attribution exist. Rules-v1/rules-v2 remain champion. No production ML model is trained. All prediction tasks are DATA_COLLECTION. Ready for a controlled PILOT tenant is not the same as unrestricted enterprise production.

## COMPLETED

- Architecture docs 00–44, diagrams, Cursor rules
- Auth, multi-tenancy, RBAC, audit, feature flags
- CRM core, scoring, Closed Won customer + onboarding/health, Command Center
- AI runtime, RAG, copilot, Approval Center
- Industry-grade command plane
- Phase 7 Market: markets, signals, triggers, deterministic scores, mock providers
- Phase 8 Acquisition: inbound capture, consent/opt-out, email/fuzzy dedupe review
- Phases 9–22 lifecycle: campaigns/ABM, sequences, conversations, meetings, deal risk, CPQ math, forecast snapshots, onboarding, health, renewals, whitespace, advocacy, model cards, persisted playbook runs
- Gated autonomy: Apify/mock discovery, persisted Autopilot, ads launch via Approvals, voice notes + gated dial
- Autopilot control plane (batch 1): `autopilot_settings`, entity automation state, idempotent event consumer, reconcile cycle, MockEmailProvider on approve, Home/Autopilot/Approvals consoles
- Live engagement loop (batch 2): encrypted Google OAuth, Gmail/Calendar providers, ActionDispatcher, inbound inbox + reply classification, mock or live booking, Integrations desk
- Post-sale revenue autopilot (batch 3): Contract + activation chain, onboarding templates, evidence-only health/risk, renewal windows, expansion recommendations (no auto Opportunity), advocacy-rules-v1, Customer 360, Home attention, Autopilot lifecycle lanes
- Live channel execution (batch 4): ICP query builder + harvestapi filters, discovery budgets/provenance/dedupe, ads pause/status/metrics + budget governance + launch idempotency, voice consent/channel + Autopilot-queued dials + Twilio/Vapi callbacks, persist-then-async inbox, circuit breaker, dead letters, ActionDispatcher registry, Prometheus provider counters, Autopilot/Integrations LIVE|MOCK|NOT CONNECTED
- Production hardening (batch 5): Postgres RLS + `set_config` tenant context, refresh-token family reuse, webhook routing tokens, SecretProvider, seed/demo guards, pgvector retrieve path, ObjectStorageProvider, OpenAPI codegen + CI drift, backup/restore scripts, dead-letter inspect + REQUESTED sweep, SSE + 5s polling, emergency/channel kill switches, OTel hook, Grafana/alerts, non-root images, Kustomize overlays, CI security baseline
- Enterprise data + live customer intelligence (batch 6): Alembic `011` signal/rollup/mapping/watermark/dirty/ML-label tables, generic signed webhooks on the Batch 5 route, identity mapping review, rules-v2 health + coverage, dirty-flag Autopilot, utilization vs ContractLine, finance/support snapshots without overwriting Contract. Docs 39–44.
- Revenue intelligence data foundation (batch 7): Alembic `012` task/feature-set/label/dataset/experiment/model/prediction tables, opportunity history, readiness gates, shadow-only inference, delayed evaluation, `/models` honesty. Docs 45–51. ADRs 023–028. Prediction tasks: all DATA_COLLECTION.
- Controlled production pilot (batch 8): Alembic `013`, `tenants.operating_mode`, Pilot Readiness API/UI, IntegrityError idempotency, email `provider_actions`, Beat heartbeat, provider precedence, WhatsApp NOT_CONFIGURED, malware quarantine, mapping unlink, health rebuild, close-lost/churn/expansion outcomes, ROI/traces/briefs, docs 52–57, ADRs 029–035. CI RLS fail-if-empty, concurrency, E2E-LITE + E2E-POSTGRES.
- Full-funnel completion: Alembic `014`–`016`, tenant credential execution, Exotel/Vapi split, India compliance gates, Recall/manual meeting capture, ads depth + campaigns UI, enrichment, public forms, campaign ROAS.
- Channel search: keyword search grouped by Google, Facebook, Instagram, and LinkedIn. Rank is the Google result position. Missing search credentials stay `not_configured` and invent no posts. Alembic `024`.
- Website signals: a confirmed catalog of public website facts, a free page reader, and a cohort whose first line is one of those facts. It does not discover leads, enroll sequences, or send mail. Alembic `031`.
- Social Growth Autopilot (fixtures): source-backed brand facts, several Pages and Instagram accounts per workspace, an approved strategy and rolling 30-day calendar, brand-template images, carousels, and 9:16 Reels behind quality gates, gated publishing with reconciliation, insight read-back with freshness, tracking links, a GA4 boundary, and the Social Growth Command Center. Alembic `046`. Doc 61. ADRs 041–045.

## IN PROGRESS

None.

## BLOCKED

- Social Growth live verification: needs a Meta app with Advanced Access to the Page and Instagram permissions, client Page and Instagram tokens, a public HTTPS `PUBLIC_API_BASE_URL` with shared object storage, and an authorized workspace.

## NEXT

Follow `docs/63-social-growth-live-acceptance.md` on an isolated staging stack. Do not run those external steps without a separate approval for each one.

After one verified token and one approved post, the next build is a Meta Ads Autopilot with closed-loop organic optimization: paused campaign assembly is already fixture-tested; a later loop may change pillar weights only from stored live readings, still behind the same grant and scope gates. Live WhatsApp when credentials exist, Gmail Pub/Sub after measured ingest lag, live Zendesk/Stripe HTTP, HNSW after measured chunk latency, and trained ML only after a task is READY_FOR_EXPERIMENT remain on the roadmap. A public HTTPS host is required before provider callbacks can reach a non-local API.

## TECHNICAL DEBT

See TECHNICAL_DEBT.md.

## ARCHITECTURE DECISIONS

See DECISIONS.md.

## TEST STATUS

- API: pytest SQLite suite + ruff; Postgres RLS job in CI
- Web: vitest, lint, tsc, next build
- Playwright: Autopilot, engagement, post-sale, providers, Batch 5 hardening, Batch 6 signals, Batch 7 intelligence admin, Batch 8 pilot readiness / trace / mapping, Social Growth (fixture accounts, creative review, attribution, read-only, cross-tenant)
- docker compose config: valid
- CI: RLS fail-if-empty, Postgres concurrency/chaos, E2E-LITE + E2E-POSTGRES
