# Backlog

Format: Epic | Feature | Task | Priority | Phase | Dependencies | Status | Acceptance Criteria

| Epic | Feature | Task | Priority | Phase | Dependencies | Status | Acceptance Criteria |
|---|---|---|---|---|---|---|---|
| Platform | Docs | Architecture set 00–33 | P0 | 0 | None | Done | Docs exist and match locked decisions |
| Platform | Rules | Cursor rules | P0 | 0 | None | Done | Five rule files enforce tenancy, AI path, security |
| Platform | Scaffold | Monorepo + Compose | P0 | 0 | Docs | Done | Compose file valid; health endpoints implemented |
| Platform | Auth | Login, refresh, logout, me | P0 | 1 | Scaffold | Done | Argon2, JWT, rotating refresh, audit on login |
| Platform | Tenancy | tenant_id isolation | P0 | 1 | Auth | Done | Cross-tenant read returns 404 |
| Platform | RBAC | Permission strings | P0 | 1 | Auth | Done | Domain checks permissions, not role names |
| Platform | Flags | Tenant feature flags | P1 | 1 | Auth | Done | Flags readable via API and UI |
| Revenue | Accounts | CRUD + 360 header | P0 | 2 | Auth | Done | Tenant-scoped CRUD, audit |
| Revenue | Contacts | CRUD | P0 | 2 | Accounts | Done | Consent fields stored |
| Revenue | Leads | CRUD + score | P0 | 2 | Accounts | Done | 100-pt deterministic score persisted |
| Revenue | Opportunities | Pipeline + close won | P0 | 2 | Accounts | Done | Closed Won creates customer + renewal stub |
| Revenue | Tasks | CRUD | P0 | 2 | Auth | Done | Linked to CRM entities |
| Revenue | Timeline | Activities | P0 | 2 | CRM | Done | Unified activity list on records |
| Revenue | ICP | Manual ICP | P1 | 2 | Auth | Done | Used by scoring |
| Intelligence | KPIs | Command Center | P0 | 3 | CRM | Done | Real SQL aggregates, empty when zero |
| AI | Runtime | Providers, tools, traces | P0 | 4 | Auth | Done | No LLM SQL; usage logged |
| AI | Approvals | Approval Center | P0 | 4 | Runtime | Done | Level 2+ queued |
| AI | RAG | Upload, chunk, retrieve | P0 | 5 | Runtime | Done | Tenant-filtered citations or abstain |
| AI | Copilot | Summaries, research, draft | P0 | 6 | RAG | Done | Draft stored; send not executed |
| Revenue | Search | Global search | P0 | 6 | CRM | Done | Tenant-scoped hits by permission |
| Revenue | Import | CSV preview/commit | P1 | 6 | CRM | Done | Preview required; 200-row cap |
| Revenue | 360 | Account context + meeting prep | P0 | 6 | CRM/AI | Done | Live contacts/opps/tasks; tool-grounded brief |
| Web | Desk | Industry command plane | P0 | 6 | CRM | Done | Create/edit/search/filter; no fake KPIs |
| Growth | Market | Signals and research | P0 | 7 | Copilot | Done | Scored markets; labeled mock providers |
| Growth | Capture | Inbound + dedupe | P0 | 8 | Market | Done | Consent respected; uncertain matches reviewed |
| Growth | Campaigns | ABM and paid | P2 | 9 | Capture | Done | Campaigns + ABM plays; paid spend is ledger-only |
| Growth | SDR | Sequences | P2 | 10 | Acquisition | Done | Enroll honors consent; send stays in Approvals |
| Engage | Voice/chat | Transcripts | P2 | 11 | Sequences | Done | Consent required; no dialer |
| Engage | Meetings | Recaps | P2 | 12 | Voice | Done | Human notes; prep remains on account 360 |
| Win | Deal intel | Risk flags | P1 | 13 | Pipeline | Done | rules-v1 flags persisted |
| Win | Commercial | Quotes | P1 | 14 | Deal intel | Done | Deterministic totals; 10%+ discount approval |
| Win | Forecast | Snapshots | P1 | 15 | Commercial | Done | SQL pipeline math; not ML |
| Succeed | Onboarding | Plans | P1 | 16 | Close won | Done | Minted on Closed Won |
| Succeed | Health | Score | P1 | 17 | Onboarding | Done | rules-v1 + labeled mock usage |
| Succeed | Renewal | Stubs | P1 | 18 | Close won | Done | Desk over existing renewal rows |
| Succeed | Expansion | Whitespace | P2 | 19 | Catalog | Done | Account × product propensity |
| Succeed | Advocacy | Refs | P2 | 20 | Success | Done | Assets + referrals |
| RevOps | Models | Cards | P2 | 21 | Scores | Done | rules-v1 cards; no trained metrics |
| RevOps | Playbooks | Runs | P1 | 22 | Workflow | Done | Persisted runs; task/activity/approval only |
| Autonomy | Discovery | Apify provider | P0 | 23 | ICP | Done | Persist discovered leads; dedupe; mock if down; human add stays |
| Autonomy | Autopilot | Persisted cycle | P0 | 23 | Discovery | Done | Runs desk; gates refuse no-consent send |
| Autonomy | Autopilot | Control plane batch 1 | P0 | 24 | Cycle | Done | Event intake + reconcile; mock send on approve; no fake people |
| Autonomy | Email | Live Gmail | P0 | 25 | Control plane | Todo | OAuth, send, reply ingest |
| Autonomy | Calendar | Live Google Calendar | P1 | 25 | Email | Todo | Booking + busy lookup |
| Autonomy | Success | Post-sale autopilot | P1 | 26 | Control plane | Todo | Health, renewal, expansion, advocacy events |
| Autonomy | Ads | Launch via Approvals | P1 | 23 | Campaigns | Done | Mock unless LinkedIn/Meta keys; no fake spend |
| Autonomy | Voice | Notes + gated dial | P1 | 23 | Meetings | Done | Extract via tool; dial needs consent + approval |
