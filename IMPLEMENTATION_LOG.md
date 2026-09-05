# Implementation Log

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
