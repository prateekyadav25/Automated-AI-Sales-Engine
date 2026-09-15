# 43 — External Identity Mapping

`external_entity_mappings` stores `provider + entity_type + external_id` → internal customer or account.

Resolution order: confirmed mapping → account domain → contract / billing id. Fuzzy company name creates a `pending` row and a lightweight `mapping.confirm` approval. Humans Confirm, Change, or Ignore on Integrations. Autopilot never auto-maps on name.

Demo tenants get deterministic routing tokens for `usage`, `support`, `finance`, and `erp`.
