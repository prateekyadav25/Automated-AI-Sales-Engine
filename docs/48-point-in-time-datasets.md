# 48 — Point-in-time datasets

`DatasetBuilder` (`app.services.ml.dataset`) takes `task_key`, date range, `feature_set_version`, and `label_version`.

Output is a `DatasetVersion` plus `TrainingExample` rows that reference snapshots (no duplicated fat JSON).

## Guarantees

- Scope is `TENANT_LOCAL`. Any other scope is rejected.
- Snapshots with `as_of` after the prediction time fail the build.
- Known leakage features (for example `closed_won_at` on `OPPORTUNITY_WIN`) fail the build.
- Fingerprint is SHA-256 of sorted `(entity_id, as_of, feature_set_version, label_version, label_status, label, features_hash)`.
- Same inputs produce the same fingerprint or the build is treated as broken.

## Splits

Default is temporal, not random: 70% / 15% / 15% by each entity's earliest `as_of`. All rows for one entity stay in one split.

Time-aware validation is the default for future cross-validation. Do not shuffle future into the past.

## Quality

Missingness, class distribution, and coverage are stored on the dataset. Missingness above `ML_MAX_MISSINGNESS` fails the build.

## Artifacts

JSONL is written to object storage at `tenant/{tenant_id}/models/{task_key}/{version}/dataset.jsonl`. Metadata stays in Postgres.

## Readiness

A task becomes `READY_FOR_EXPERIMENT` only when configurable minimums are met (defaults: 200 rows, 40 positive, 40 negative, 90 days of history). Demo seed does not meet them. That is correct.
