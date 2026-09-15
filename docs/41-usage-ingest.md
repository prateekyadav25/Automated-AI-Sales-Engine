# 41 — Product Usage Ingest

`GenericUsageWebhookProvider` is ingest-only. Public path: `POST /api/v1/webhooks/usage/{routing_token}` (alias `POST /api/v1/integrations/product-usage/events/{routing_token}`).

Accepted event types: `user.active`, `user.login`, `feature.used`, `workflow.executed`, `api.requested`, `seat.assigned`, `seat.active`, `capacity.used`, `license.limit_approaching`, `product.error`.

Dedupe is `(tenant_id, provider, external_id)`. Customer resolution never trusts body `tenant_id` or an unmapped `customer_id`. Domain, confirmed mapping, or contract/billing id can confirm. Company-name match stays `pending`.

Deterministic rollups: DAU / WAU / MAU, licensed seats from `ContractLine`, utilization %, feature breadth/depth, 7/30/90-day trend, `last_usage_event_at`. High utilization opens an upsell recommendation. Low utilization is `ADOPTION_RISK`, not expansion. Amounts stay null unless a price book exists.
