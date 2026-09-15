# Implementation Log

## 2026-09-12 (Full-funnel completion)

- Phase 0: tenant `ProviderAccount` secrets feed ads, voice, and discovery factories. Debug ingest removed. React `error.tsx` added. Voice docs no longer claim there is no dialer.
- Phase 1: `provision_env_credentials` copies deployment secrets into tenant rows. `activate_mode` provisions, then fail-closes. Channels report LIVE from a tenant credential when one exists.
- Phase 2: `VoiceTelephonyProvider` / `VoiceConversationProvider`, Exotel + region router, NDNC/TRAI/recording gates, Vapi + human handoff, versioned voice scripts, Alembic `014`.
- Phase 3: `MeetingCaptureProvider` (Recall, upload STT, manual), consent-gated bot join, transcript-only `meeting_intelligence`, meetings UI, Alembic `015`.
- Phase 4: LinkedIn/Meta ad sets, creatives, ads, activate, consented audience sync, persisted CTR/CPC/CPL, pause/sync UI, Alembic `016`.
- Phase 5: `ContactEnrichmentProvider`, public key-scoped capture + embeddable form, campaign/ad/UTM on Lead/Opportunity, spend-vs-closed-revenue ROI.
- Phase 6: `TOKEN_ENCRYPTION_KEY`, `METRICS_TOKEN`, ClamAV, and `PUBLIC_API_BASE_URL` are set in local `.env` (gitignored). PRODUCTION readiness now fail-closes without encryption, HTTPS callbacks, metrics auth, and malware. `ML_ALLOW_CHAMPION` remains false. Aikido scan requires an Aikido sign-in in this workspace.

## 2026-09-11 (Controlled production pilot batch 8)

- Gap note `docs/52-pilot-readiness-gap-analysis.md`. Runbooks `docs/53`–`docs/57`. ADRs 029–035.
- 8A: Alembic `013` tenant mode, settings versions, WhatsApp consent/templates, outcomes, quality, briefs, overrides, heartbeats. `pilot.view` / `pilot.activate`. Fail-closed activate. Admin Pilot Readiness page. CI RLS fail-if-empty, concurrency job, E2E-LITE + E2E-POSTGRES.
- 8B: `claim_key` / `begin_action` IntegrityError recovery, `FOR UPDATE` on close-won, email in `provider_actions`, Beat heartbeat + `scheduler_unhealthy`, execute-time staleness, AI daily budget fail-closed.
- 8C: Provider precedence, encrypted LinkedIn/Meta/Twilio/Vapi rows, WhatsApp NOT_CONFIGURED path, malware quarantine, mapping unlink + recalc, health rebuild, immutable snapshots + lineage, config export.
- 8D: Close lost / churn / expansion outcomes, data quality, ROI methodology, full traces, daily/weekly briefs, readiness notify without training.
- 8E: Playwright pilot paths, `scripts/pilot_load.py` (measured only), status files distinguish controlled PILOT from unrestricted production.

## 2026-09-11 (Revenue intelligence data foundation batch 7)

- Gap note `docs/45-revenue-intelligence-gap-analysis.md`. Architecture notes `docs/46`–`docs/51`. ADRs 023–028.
- 7A: Alembic `012` extends feature snapshots/labels/model cards; adds prediction tasks, feature sets, label definitions, training examples, datasets, experiments, model versions, predictions, evaluations, drift baselines, opportunity/entity history, recommendation feedback. FORCE RLS. `ml.view|dataset.create|train|promote|rollback`.
- 7B: Deterministic `compute_features` with `as_of`. Opportunity field history on create/patch/close-won. Versioned labels with PENDING/CENSORED. Outcomes use event time.
- 7C: `DatasetBuilder` is tenant-local, fingerprinted, temporally split, rejects leakage and future observations. Readiness gate defaults 200/40/40/90. CLI `python -m app.ml`.
- 7D: `RulesPredictionProvider` is champion. Challengers may write SHADOW predictions only. `ACTIVE` ML rejected. Daily `ml_evaluate_matured`. Training jobs exist and refuse unless ready.
- 7E: `/models` shows readiness, datasets, NO TRAINED MODEL, Challenger: none. No fake accuracy. Autopilot stays on rules.

## 2026-09-11 (Enterprise data + live customer intelligence batch 6)

- Gap note `docs/39-enterprise-data-integration-gap-analysis.md`. Architecture notes `docs/40-customer-signal-architecture.md` through `docs/44-customer-health-v2.md`.
- 6A: Alembic `011` `customer_signals`, `usage_events`, `usage_rollups`, support/finance snapshots, `external_entity_mappings`, watermarks, dirty intelligence, ML feature/outcome tables, FORCE RLS. Inbox routes usage/support/finance/erp away from email. Mapping service: explicit → domain → contract id; fuzzy name stays pending.
- 6B: Generic usage webhook, event-id dedupe, DAU/WAU/MAU rollups, STALE ≠ zero, utilization vs `ContractLine`. High util → upsell rec. Low util → `ADOPTION_RISK`.
- 6C: Generic support/finance/ERP webhooks, upsert/void, `COMMERCIAL_DATA_MISMATCH` task. Vendor stubs stay `NOT_CONFIGURED`.
- 6D: Health `rules-v2` + coverage, same-version trend, dirty-flag Autopilot, risk/renewal/expansion/advocacy evidence, unused NBA generators wired. Feature snapshots and outcome labels collect; no training.
- 6E: Customer 360 freshness cards, Integrations mapping review, Autopilot/Command Center evidence aggregates, Prometheus series without `customer_id` labels, Grafana alert stubs.

## 2026-09-11 (Production hardening batch 5)

- Gap note `docs/35-production-readiness-gap-analysis.md`. Runbooks `docs/36-disaster-recovery.md`, `docs/37-incident-response.md`, checklist `docs/38-production-readiness-checklist.md`.
- 5A: Alembic `009` RLS roles (`agrayian_app` without BYPASSRLS), parameterized `set_config` tenant context, refresh-token families + session APIs, webhook routing tokens (no `X-Tenant-Id`), log redaction, auth rate limits, production seed/demo guards, SecretProvider, `/health/live` + `/health/ready`.
- 5B: Alembic `010` pgvector column + uniqueness, `ObjectStorageProvider` (local/MinIO/S3), knowledge byte persist + download, OpenAPI codegen + drift check, backup/restore scripts.
- 5C: Dead-letter inspect on Autopilot (pagination, attempts, timestamps), `reconcile_requested_actions` for stuck REQUESTED, SSE + 5s polling, emergency/channel kill switches, approval `expires_at`, voice execute re-checks `assert_can_dial`, pagination on activities/runs/approvals/audit/actions, OTel hook, Prometheus HTTP + dead-letter series, Grafana JSON + alerts.
- 5D: Non-root Dockerfiles, Kustomize base + staging/production overlays, migrate Job, CI OpenAPI/RLS/alembic/gitleaks/audit/Bandit/image build. ADRs 014–020.

## 2026-09-11 (Live channel execution batch 4)

- Gap note `docs/34-provider-execution.md`. Alembic `008_live_channels`: ICP filter fields, lead provenance, contact channel/voice consent, campaign external id/metrics, conversation `call_status`, discovery budgets, inbox status/attempts, `provider_actions`, `provider_health_states`.
- Explicit provider modes. Live without credentials is NOT_CONFIGURED. Live HTTP failure never swaps to mock. Mock discovery still returns zero people.
- Discovery: deterministic ICP → harvestapi query builder, validation/provenance, LinkedIn URL / provider_ref / person dedupe, run and candidate budgets on Autopilot and `POST /discovery/run`.
- Ads: pause/status/metrics protocol, budget governance, `ads.launch:{tenant}:{approval_id}` idempotency, persist external id only after confirmation, Celery `sync_ad_campaigns` every 5 minutes, derived CTR/CPC/CPL only when inputs exist.
- Voice: `VAPI_ASSISTANT_ID` / `VAPI_PHONE_NUMBER_ID` / `VAPI_WEBHOOK_SECRET`, `assert_can_dial` uses voice consent + preferred channel, Autopilot queues eligible dials, Twilio/Vapi callbacks, transcript + deterministic outcome routing (DNC / follow-up / nurture / meeting).
- Ops: persist-then-async inbox, failure classes, circuit breaker, dead-letter APIs, ActionDispatcher registry, Prometheus provider counters, Autopilot/Integrations LIVE|MOCK|NOT CONNECTED, no secrets in UI.
- ADR-013: process-level vendor credentials; Google remains the only per-tenant OAuth. External systems are at-least-once; business effects are effectively-once via inbox uniqueness, action keys, and state checks.

## 2026-09-11 (Post-sale revenue autopilot batch 3)

- Alembic `007_post_sale_autopilot`: contracts, handoff packages, onboarding templates, health snapshots, customer risks, usage snapshots, product relationships, expansion recommendations, AI artifacts. Additive Customer/Renewal/milestone/advocacy columns and Autopilot post-sale flags.
- Closed Won activates once per opportunity (`customer.activation:{tenant}:{opportunity}`): owners, Contract from won Quote (unknown term/escalation stay null), HandoffPackage + HandoffAgent, default 8-milestone onboarding, renewal, success plan, rules-v1 health, NBA, handoff task.
- Health v2 is evidence-only. Mock usage and unavailable support/finance are labeled and excluded from the total. Snapshots carry a real trend. `churn-rules-v1` raises risks; CustomerSuccessAgent drafts only.
- Renewal windows 180/120/90/60/30 with no duplicate window events. Baseline comes from the contract and stays `needs_review` when escalation is unknown. RenewalAgent brief + `renewal.commercial` approval.
- Expansion Autopilot refreshes whitespace and catalog adjacency. Recommendation `amount` is null. Opportunity minting is approval-gated and off by default.
- `advocacy-rules-v1` eligibility. Quotes stay null. Referral ingest creates a Lead with `source=referral` and `consent_email=false`.
- Orchestrator routes post-sale events. Celery Beat: frequent 5m, daily 24h, weekly 7d. Cycle step 6 runs frequent + daily. Customer 360, Home attention, Autopilot lanes ACQUIRE/SELL/SUCCEED/RETAIN/GROW/ADVOCATE, Approval categories.
- Pytest journeys 1–7 + cross-tenant 404. Playwright closed-won → customer automation → Autopilot activity → renewal. SSE still deferred.

## 2026-09-06 (Live engagement loop batch 2)

- Alembic `006_live_engagement`: `provider_accounts`, `email_messages`, `provider_inbox_events`, conversation/meeting/settings columns. Fernet helpers for integration tokens.
- Google OAuth connect/callback/disconnect. `GmailEmailProvider` + `GoogleCalendarProvider` with Outlook/Microsoft stubs. Tenant-aware factories. Live mode does not fall back to mock.
- `ActionDispatcher` executes send/calendar/ads/voice. Send gates: consent, pause, quiet hours, daily/contact/gap limits, pending-then-approved, `email.send:{tenant}:{approval_id}`. Enrollment steps advance after send.
- Inbound: Beat history sync, webhook persist-then-process, mock `/inbox/simulate`. ReplyIntelligence + deterministic router. Unsubscribe wins.
- Calendar owner fallback, deterministic slots, book/reschedule/cancel. `lead.status=meeting_scheduled`. Integrations desk + Autopilot health (Gmail / Google Calendar, MOCK not a config block).
- Pytest engagement suite + Playwright journeys 1–5. SSE remains debt.

## 2026-09-05 (Autopilot control plane batch 1)

- Settings, entity automation state, and idempotency keys in Alembic `005_autopilot_control_plane`. Seed writes default settings (`enabled=true`) and syncs `ENABLE_AUTOPILOT`.
- `RevenueOrchestrator` consumes `domain_events`. Lead intake: enrich → score → qualify → research → NBA → enroll or Blocked by policy. `score_lead` emits `lead.scored`. `research_account` no longer commits.
- Reconcile cycle honors settings and skips disabled tenants. Celery Beat: outbox every 1 min, cycles every 15 min. Compose `beat` service.
- Approve `*.send` enrolls if needed, sends via MockEmailProvider, persists activity + provider id, emits `email.sent`. Edit & Approve and entity pause are on the card.
- APIs: settings, status, activity, entity trace, pause/resume/retry. Home, Autopilot console, Approvals evidence, lead/account Automation section. UI polls every 5s.
- Pytest journeys: consented intake, mock send, no-consent block, disabled skip, entity pause. Existing suite 50 passed. Playwright smoke + CI e2e job.

## 2026-08-22 (autonomy Phases 2–5)

- Lead discovery: `LeadDiscoveryProvider` (Apify official API or labeled mock). Persist Lead/Account/Contact with `source=ai_discovery`, email/person dedupe, DNC skip. Human add and CSV import stay (`human` / `import`).
- Autopilot: `autonomous_runs` + steps, `run_autonomous_cycle` (discover → markets → rescore → consent-only send queue → ads Approvals). Desk `/automation/runs`. Celery `run_autonomous_cycles`.
- Ads: `AdsProvider` mock + LinkedIn/Meta adapters. Campaign Launch → `ads.spend` approval. No invented CTR/spend.
- Voice: `VoiceProvider` mock + Twilio/Vapi. Dial requires consent + `voice.dial` approval. Meeting extract uses approved LLM tool and cites/abstains.
- API: 45 pytest passed. Web lint/tsc passed.

## 2026-08-22 (autonomy Phase 1 — UI)

- Contacts list and detail now return `account_name` from a tenant-scoped account join.
- ICP industries and geographies render as wrapping chips.
- API: `tests/test_contacts.py` (2 passed). Web lint/tsc passed.

## 2026-08-18

- Created Cursor rules and docs/00–33.
- Scaffolded monorepo: Next.js web, FastAPI API, Celery worker, Compose, CI workflow.
- Implemented Phase 1: tenants, JWT/refresh, RBAC, teams, territories, audit, flags.
- Implemented Phase 2: CRM core, deterministic lead scoring, Closed Won customer/renewal stubs.
- Implemented Phase 3: Command Center KPIs from SQL.
- Implemented Phases 4–6: mock/OpenAI providers, agent runtime, tools, RAG, copilot, email drafts, Approval Center.
- Seeded fictional BFSI/gov/manufacturing/healthcare/retail/tech/enterprise demo data.
- Validation: pytest 12 passed; vitest 3 passed; web lint/typecheck/build passed; compose config valid.

## 2026-08-18 (gap-fill + desk)

- Closed Phase 0–6 product gaps: PATCH for contacts/leads/ICPs, task search, account 360, global search, CSV import, command-center overview, meeting prep.
- Rebuilt the web desk to an industry command plane: Manrope/Newsreader, gold/ivory graphite, command palette, copilot drawer, kanban pipeline, create/edit drawers, search/filter/pagination.
- Added ICP, customers, import, teams, contact/task detail, and designed-empty later-engine pages.
- Validation: API 16 passed + ruff; web lint/tsc/vitest 4 passed/next build passed.

## 2026-08-19 (Phases 7–8)

- Phase 7 Market Intelligence: markets, five signal types, triggers, rules-v1 scoring, mock company/intent/news/tech providers, refresh + research tools.
- Phase 8 Acquisition: inbound capture with UTM/consent, opt-out refusal, email and fuzzy-name dedupe review. Sequences and paid ads remain later.
- UI: `/market`, `/market/signals`, `/market/triggers`, `/acquisition`. Success stays coming-soon.
- Validation: API 21 passed + ruff.

## 2026-08-19 (Phases 9–22)

- Lifecycle engines: campaigns/ABM, sequences (consent + Approval Center), conversations (no dialer), meetings, deal risk rules, deterministic quotes, forecast snapshots, onboarding + health on Closed Won, renewals desk, whitespace, advocacy/referrals, rules-v1 model cards, persisted playbook runs.
- Closed gaps: command-center lifecycle pulse, account 360 health/meetings/quotes/whitespace, customers show account name, Success coming-soon redirected to the live desk.
- Seed: Helios Closed Won path, Meridian quote, Jane sequence enrollment, mock conversation, playbook run.
- Validation: see PROJECT_STATUS.md.
