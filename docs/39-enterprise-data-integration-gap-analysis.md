# 39 — Enterprise Data Integration Gap Analysis

Batch 6 audit of AGRAYIAN Autonomous Revenue OS after Autopilot batches 1–5. Classifications:

- **DONE** — implemented and used by Autopilot
- **PARTIAL** — abstraction or UI exists but does not ingest live enterprise data
- **MOCK** — labeled mock only; never treated as live evidence
- **UNAVAILABLE** — provider returns unavailable / not configured
- **MISSING** — not in the repository

Evidence is the repository at audit time, before Batch 6 implementation.

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | ProductUsageProvider protocol | **PARTIAL** | `apps/api/app/providers/usage.py` — `health` + `snapshot` only |
| 2 | Live usage ingest | **MISSING** | Factory always returns `MockProductUsageProvider` |
| 3 | Usage mock labeling | **MOCK** | `is_mock=True`, `state=MOCK`; health excludes from total |
| 4 | SupportProvider protocol | **PARTIAL** | `snapshot` only; always `UnavailableSupportProvider` |
| 5 | Live support ingest | **UNAVAILABLE** | `state=NOT_CONFIGURED`; no snapshot table |
| 6 | FinanceProvider protocol | **PARTIAL** | `snapshot` only; always `UnavailableFinanceProvider` |
| 7 | Live finance ingest | **UNAVAILABLE** | `state=NOT_CONFIGURED`; no snapshot table |
| 8 | ERP / subscription provider | **MISSING** | No protocol |
| 9 | CustomerSignal model | **MISSING** | No table or service |
| 10 | Signal provenance (freshness, mock, observed_at) | **PARTIAL** | Usage snapshot has `is_mock` + `last_activity_at`; no STALE |
| 11 | Product usage webhooks | **MISSING** | Inbox treats unknown providers as email |
| 12 | Usage event types + dedupe | **MISSING** | No `usage_events` |
| 13 | DAU/WAU/MAU rollups | **MISSING** | Health reads mock snapshot integers |
| 14 | STALE vs zero usage | **MISSING** | Silence is not distinguished from zero |
| 15 | Support webhooks + tickets | **MISSING** | No ticket upsert |
| 16 | Support → health scoring | **PARTIAL** | Component recorded UNAVAILABLE; never scored when live |
| 17 | Finance webhooks + invoices | **MISSING** | No invoice upsert |
| 18 | Commercial payment health | **PARTIAL** | UNAVAILABLE only; ARR commercial component is CRM-only |
| 19 | ExternalEntityMapping | **MISSING** | No durable external↔internal map |
| 20 | Identity resolution (no name auto-map) | **MISSING** | Inbox matches email for leads only |
| 21 | Mapping review UI | **MISSING** | Integrations desk is Google + channel modes |
| 22 | Contract entitlements vs usage | **PARTIAL** | `Contract`/`ContractLine` exist; seats unused (mock null) |
| 23 | Utilization / underutilization | **PARTIAL** | Expansion upsell gate exists but never fires |
| 24 | Feature-level whitespace | **PARTIAL** | Catalog whitespace only; no `feature.used` evidence |
| 25 | Health rules-v1 | **DONE** | Evidence-only; mock excluded |
| 26 | Health rules-v2 + coverage | **MISSING** | Single live row; no coverage metric; trend ignores version |
| 27 | Health reason codes | **PARTIAL** | `reason_codes_json` lists unavailable names |
| 28 | Meaningful health_changed | **PARTIAL** | Fingerprint + ±4 trend; still daily full scan |
| 29 | Customer risk from live signals | **PARTIAL** | `churn-rules-v1` uses CRM/health trend only |
| 30 | Autopilot CS intervention | **DONE** | Risk → success agent → task → approval |
| 31 | Renewal readiness live evidence | **PARTIAL** | `rules-v1` from health + risks + ARR |
| 32 | Renewal why-ready / why-risk UI | **MISSING** | Score + factor list only |
| 33 | Upsell from utilization | **PARTIAL** | 85% seats when non-mock |
| 34 | Cross-sell from usage evidence | **PARTIAL** | Whitespace + catalog adjacency |
| 35 | Advocacy vs critical support | **PARTIAL** | Blocks on high CRM risks, not tickets |
| 36 | Customer 360 usage/support/finance cards | **PARTIAL** | Usage mock label; no support/finance/freshness |
| 37 | Provider health Usage/Support/Finance | **PARTIAL** | Autopilot lists them; Integrations UI filters them out |
| 38 | Webhook tenant mapping | **DONE** | Batch 5 routing tokens; strips body `tenant_id` |
| 39 | Inbox for usage/support/finance | **MISSING** | Non-voice → email path |
| 40 | Integration watermarks / backfill | **PARTIAL** | Google `last_history_id` only |
| 41 | Per-tenant enterprise credentials | **PARTIAL** | `ProviderAccount` is Google-user OAuth |
| 42 | Dirty-flag customer recalc | **MISSING** | Daily scan of all customers |
| 43 | ML outcome labels / feature snapshots | **MISSING** | `last_trained` null; no label tables |
| 44 | Dead letters for ingest | **DONE** | Provider actions + Autopilot inspect |
| 45 | RLS on new signal tables | **MISSING** | Tables do not exist |
| 46 | WhatsApp / Gmail Pub/Sub / Slack | **MISSING** | Intentionally deferred |

## Honest mocks that stay

`MOCK`, `UNAVAILABLE`, `NOT_CONFIGURED`, and (after Batch 6) `STALE` remain labels. Generic webhooks are the first live path. Zendesk / Freshdesk / ServiceNow / Stripe stay `NOT_CONFIGURED` stubs. No trained ML.
