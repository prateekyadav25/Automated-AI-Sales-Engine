# Project Status

## CURRENT PHASE

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

## IN PROGRESS

None.

## BLOCKED

None.

## NEXT

Live WhatsApp adapter when credentials exist, Gmail Pub/Sub after measured ingest lag, live Zendesk/Stripe HTTP, HNSW after measured chunk latency, trained ML only after a task is READY_FOR_EXPERIMENT and a human starts one SHADOW experiment. A public HTTPS host is required before Exotel/Twilio/Vapi/Recall/Gmail callbacks can reach a non-local API.

## TECHNICAL DEBT

See TECHNICAL_DEBT.md.

## ARCHITECTURE DECISIONS

See DECISIONS.md.

## TEST STATUS

- API: pytest SQLite suite + ruff; Postgres RLS job in CI
- Web: vitest, lint, tsc, next build
- Playwright: Autopilot, engagement, post-sale, providers, Batch 5 hardening, Batch 6 signals, Batch 7 intelligence admin, Batch 8 pilot readiness / trace / mapping
- docker compose config: valid
- CI: RLS fail-if-empty, Postgres concurrency/chaos, E2E-LITE + E2E-POSTGRES
