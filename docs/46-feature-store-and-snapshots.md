# 46 — Feature store and snapshots

Feature engineering is code. An LLM does not calculate numeric training features.

## FeatureSnapshot

Persisted in `ml_feature_snapshots` (extended, not forked):

- `tenant_id`, `entity_type`, `entity_id`, `customer_id`
- `task_key`, `feature_set_version`
- `as_of` — the only legal clock for the row
- `features_json`, `source_versions_json`
- `immutable` — service refuses payload updates

Unique key: `(tenant_id, entity_type, entity_id, task_key, feature_set_version, as_of)`.

A training row for time T contains only data with `changed_at` / `created_at` / `observed_at` ≤ T.

## FeatureSet

`feature_sets` stores versioned definitions: name, type, source, calculation, window, null behavior, freshness, version.

Never change the meaning of a feature under the same `feature_set_version`. Add `v2`.

## Deterministic pipeline

`app.services.ml.features.compute_features` implements v1 sets for each task. Windows use `as_of`, never `now()`.

Examples: `lead_icp_score`, `lead_intent_score`, `emails_last_30d`, `meetings_last_30d`, `days_in_stage`, `close_date_change_count`, `customer_health_score`, `usage_30d_change`, `critical_support_tickets`, `days_past_due`.

LLM-derived features are allowed only when named, structured, versioned, and tagged `source=llm`. None ship in Batch 7.

## History

`opportunity_field_history` records stage, amount, probability, expected close, and owner before overwrite.

`entity_field_history` records renewal readiness and expansion status transitions.

Lead scores remain append-only. Health snapshots remain append-only.

Do not reconstruct training rows from the current Opportunity row alone.
