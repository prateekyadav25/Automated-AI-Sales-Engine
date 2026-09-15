# 40 — Customer Signal Architecture

Inbound enterprise events stay on the Batch 5 webhook path: `POST /api/v1/webhooks/{provider}/{routing_token}`. The body `tenant_id` is stripped. Tenant comes from `webhook_routes`. Inbox then dispatches `usage`, `support`, `finance`, and `erp` to signal normalizers, not email.

Normalized facts land in `customer_signals`. Raw usage events live in `usage_events` (short retention). Health reads `usage_rollups`, `support_snapshots`, and `finance_snapshots`. Identity uses `external_entity_mappings`. Dirty customers are marked in `customer_intelligence_states` so Autopilot recalculates one customer, not the whole book.

`freshness_state` is `LIVE`, `STALE`, `MOCK`, `UNAVAILABLE`, or `NOT_CONFIGURED`. STALE is not zero usage. Coverage is not the health score.
