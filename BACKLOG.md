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
| Succeed | Health | Score | P1 | 17 | Onboarding | Done | rules-v2 scores only LIVE+FRESH; coverage separate; mock/stale excluded |
| Succeed | Signals | Usage/support/finance ingest | P0 | Batch 6 | Webhooks | Done | Generic signed webhooks; mapping review; no vendor lock-in |
| Succeed | Renewal | Stubs | P1 | 18 | Close won | Done | Desk over existing renewal rows |
| Succeed | Expansion | Whitespace | P2 | 19 | Catalog | Done | Account × product propensity |
| Succeed | Advocacy | Refs | P2 | 20 | Success | Done | Assets + referrals |
| RevOps | Models | Cards | P2 | 21 | Scores | Done | rules-v1 cards; no trained metrics |
| RevOps | Playbooks | Runs | P1 | 22 | Workflow | Done | Persisted runs; task/activity/approval only |
| Autonomy | Discovery | Apify provider | P0 | 23 | ICP | Done | Persist discovered leads; dedupe; mock if down; human add stays |
| Autonomy | Autopilot | Persisted cycle | P0 | 23 | Discovery | Done | Runs desk; gates refuse no-consent send |
| Autonomy | Autopilot | Control plane batch 1 | P0 | 24 | Cycle | Done | Event intake + reconcile; mock send on approve; no fake people |
| Autonomy | Email | Live Gmail | P0 | 25 | Control plane | Done | OAuth, send, reply ingest |
| Autonomy | Calendar | Live Google Calendar | P1 | 25 | Email | Done | Booking + busy lookup |
| Autonomy | Success | Post-sale autopilot | P1 | 26 | Control plane | Done | Closed Won activates CS/renewal/expansion/advocacy; humans stay in Approvals |
| Autonomy | Ads | Launch via Approvals | P1 | 23 | Campaigns | Done | Mock unless LinkedIn/Meta keys; no fake spend |
| Autonomy | Voice | Notes + gated dial | P1 | 23 | Meetings | Done | Extract via tool; dial needs consent + approval |
| Autonomy | Channels | Live discovery/ads/voice | P0 | 27 | Control plane | Done | Explicit modes; persist-then-confirm; no silent mock fallback; budgets and callbacks |
| Autonomy | Ops | Circuit + dead letter | P0 | 27 | Channels | Done | Failure classes, provider_actions, Prometheus, operator retry/cancel |
| Platform | Hardening | Batch 5A security | P0 | 28 | Channels | Done | RLS, token family, webhook map, seed guards, auth limits |
| Platform | Hardening | Batch 5B data | P0 | 28 | 5A | Done | pgvector retrieve, object storage, OpenAPI drift, backup scripts |
| Platform | Hardening | Batch 5C ops | P0 | 28 | 5B | Done | DLQ inspect, REQUESTED sweep, SSE+poll, kill switches, OTel/metrics |
| Platform | Hardening | Batch 5D deploy | P0 | 28 | 5A+5B | Done | Non-root images, Kustomize, CI security, docs 36–38 |
| Intelligence | Signals | Batch 6A model | P0 | 29 | 5A | Done | Alembic 011, RLS, mapping, inbox dispatch |
| Intelligence | Usage | Batch 6B ingest | P0 | 29 | 6A | Done | Generic usage webhook, rollups, STALE, utilization |
| Intelligence | Support/Finance | Batch 6C ingest | P0 | 29 | 6A | Done | Snapshots, upsert/void, contract mismatch, vendor stubs |
| Intelligence | Health | Batch 6D rules-v2 | P0 | 29 | 6B+6C | Done | Coverage, dirty Autopilot, NBA wiring, labels only |
| Intelligence | Desk | Batch 6E UI/ops | P0 | 29 | 6D | Done | 360 freshness, mapping UI, evidence, docs 40–44 |
| Intelligence | ML foundation | Batch 7A schema | P0 | 30 | 6E | Done | Alembic 012, registries, RLS, ml.* permissions |
| Intelligence | ML foundation | Batch 7B PIT | P0 | 30 | 7A | Done | Snapshots, history, versioned labels, censoring |
| Intelligence | ML foundation | Batch 7C datasets | P0 | 30 | 7B | Done | Builder, fingerprint, temporal split, readiness |
| Intelligence | ML foundation | Batch 7D shadow | P0 | 30 | 7C | Done | PredictionProvider, shadow only, delayed eval |
| Intelligence | ML foundation | Batch 7E gov/UI | P0 | 30 | 7D | Done | Promote/rollback, /models honesty, docs 45–51 |
| Platform | Pilot | Batch 8A mode/gate/CI | P0 | 31 | 7E | Done | operating_mode, Alembic 013, Pilot Readiness, RLS fail-if-empty, E2E-POSTGRES |
| Platform | Pilot | Batch 8B concurrency | P0 | 31 | 8A | Done | IntegrityError claim, FOR UPDATE, chaos/heartbeat tests |
| Platform | Pilot | Batch 8C providers | P0 | 31 | 8B | Done | Precedence, WhatsApp NOT_CONFIGURED, malware honesty, unlink, snapshots |
| Platform | Pilot | Batch 8D outcomes | P0 | 31 | 8C | Done | Lost/churn/expansion, ROI, traces, briefs, notify without train |
| Platform | Pilot | Batch 8E docs/baseline | P0 | 31 | 8D | Done | Docs 53–57, ADRs 029–035, measured load script |
| Funnel | Credentials | Tenant ProviderAccount execution | P0 | 32 | 8C | Done | Ads/voice/discovery factories honor tenant rows; no silent mock fallback |
| Funnel | Voice | Telephony/conversation split | P0 | 32 | Channels | Done | Exotel India primary, Vapi/human conversation, NDNC/TRAI gates, Alembic 014 |
| Funnel | Meetings | Capture + intelligence | P0 | 32 | Voice | Done | Recall/upload/manual, consent gate, transcript-only insights, Alembic 015 |
| Funnel | Ads | Sets/creatives/audiences | P0 | 32 | Campaigns | Done | Activate, consent audience, CTR/CPC/CPL persist, Alembic 016 |
| Funnel | Supply | Enrichment + public capture | P0 | 32 | Capture | Done | Key-scoped rate-limited form; email find/verify |
| Funnel | Attribution | Spend vs closed revenue | P0 | 32 | Ads | Done | campaign_id/ad/UTM on Lead/Opp; ROI report |
| Platform | Prod | Callbacks/keys/Aikido | P1 | 32 | Hardening | Done | Local TOKEN_ENCRYPTION_KEY/METRICS_TOKEN/ClamAV set; PRODUCTION fail-closes without HTTPS callbacks; ML champion not forced; Aikido needs sign-in |
