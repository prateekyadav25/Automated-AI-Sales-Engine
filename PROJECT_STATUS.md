# Project Status

## CURRENT PHASE

Phases 0–22 plus Autopilot control plane batch 1 are in product. Enabling Autopilot runs discovery, enrichment, scoring, research, and approval queuing from persisted events and a reconcile cycle. Live Gmail/Calendar/Apify/ads/voice still require vendor keys. Sends, spend, and dial stay in Approvals. Mock email is the only send provider in this batch.

## COMPLETED

- Architecture docs 00–33, diagrams, Cursor rules
- Auth, multi-tenancy, RBAC, audit, feature flags
- CRM core, scoring, Closed Won customer + onboarding/health, Command Center
- AI runtime, RAG, copilot, Approval Center
- Industry-grade command plane
- Phase 7 Market: markets, signals, triggers, deterministic scores, mock providers
- Phase 8 Acquisition: inbound capture, consent/opt-out, email/fuzzy dedupe review
- Phases 9–22 lifecycle: campaigns/ABM, sequences, conversations, meetings, deal risk, CPQ math, forecast snapshots, onboarding, health, renewals, whitespace, advocacy, model cards, persisted playbook runs

- Gated autonomy: Apify/mock discovery, persisted Autopilot, ads launch via Approvals, voice notes + gated dial
- Autopilot control plane (batch 1): `autopilot_settings`, entity automation state, idempotent event consumer, reconcile cycle, MockEmailProvider on approve, Home/Autopilot/Approvals consoles

## IN PROGRESS

None.

## BLOCKED

None.

## NEXT

Live Gmail/Calendar (batch 2). Live Apify/ads/voice when credentials exist. Post-sale health/renewal/expansion autopilot. Trained ML only after labeled history and an explicit model card with last_trained.

## TECHNICAL DEBT

See TECHNICAL_DEBT.md.

## ARCHITECTURE DECISIONS

See DECISIONS.md.

## TEST STATUS

- API: 50 passed (pytest), ruff clean
- Web: 4 passed (vitest); lint, tsc passed
- Playwright smoke: login → Autopilot ON → Approvals heading (CI e2e job)
