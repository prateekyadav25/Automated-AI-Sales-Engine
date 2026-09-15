# 45 — Revenue Intelligence Gap Analysis

Audit date: 2026-09-11. Source: repository after Autopilot batches 1–6 (Alembic head `011`).

Classification: **DONE** | **PARTIAL** | **MISSING** | **NOT_ENOUGH_DATA** | **DEFERRED**.

Batch 7 builds the missing foundation. It does not train production models or replace `rules-v1` / `rules-v2`.

## The seven questions

| Question | Before Batch 7 | Class |
|---|---|---|
| What did we know at prediction time? | Health JSON only; opportunity/lead fields overwrite in place | PARTIAL |
| What was predicted? | Live scores exist; no `Prediction` row | PARTIAL |
| Which model/version? | `rules-v1` / `rules-v2` strings on score rows; no registry | PARTIAL |
| What features were used? | Health snapshot payload; no feature-set version | PARTIAL |
| What actually happened later? | `OPPORTUNITY_WON` only; `occurred_at` is write time | PARTIAL |
| Was the prediction correct? | No delayed join | MISSING |
| Can the exact prediction be reproduced? | No snapshot immutability, fingerprint, or code/dataset versions | MISSING |

## Existing intelligence data

| Area | Evidence | Class | Notes |
|---|---|---|---|
| Feature snapshots | `ml_feature_snapshots` via `record_features` on health recalc | PARTIAL | No `task_key`, `as_of`, `feature_set_version`, `source_versions`, immutability |
| Outcome labels | `ml_outcome_labels`; unique on outcome type | PARTIAL | Only `OPPORTUNITY_WON` wired; no version, horizon, CENSORED/PENDING |
| Lead scoring | `lead_scores` append-only, `rules-v1` | PARTIAL | Not linked to feature snapshots |
| Deal health | `deal_insights` upsert | PARTIAL | No field history |
| Forecast | `forecast_snapshots` on-demand | PARTIAL | No beat; thin columns |
| Customer health | Live `health_scores` + snapshots, `rules-v2` | PARTIAL | Snapshots exist; not task-scoped |
| Renewal readiness | `renewals` in-place | PARTIAL | No readiness history |
| Expansion recommendations | upsert | PARTIAL | No accept/reject/ignore history |
| Event history | `domain_events` | PARTIAL | Useful lineage, not a feature store |
| Activities | `activities` | PARTIAL | Usable for windows if filtered by `created_at` |
| Opportunity history | none | MISSING | PATCH overwrites stage/amount/close/probability/owner |
| Lead history | scores append; lead row mutates | PARTIAL | |
| Health history | `health_score_snapshots` | PARTIAL | |
| AI traces | agent runs / tool calls | PARTIAL | Not ML lineage |
| Model cards | name/purpose/version/notes | PARTIAL | No `last_trained`, metrics, dataset, limitations columns |
| Rules-v1 / rules-v2 | production champions | DONE | Must stay champion |
| Timestamps | mix of `created_at`, `calculated_at`, write-time `occurred_at` | PARTIAL | Label event time is wrong |

## Prediction tasks (pre-Batch 7)

All nine tasks are **MISSING** as a formal registry. Operational rules exist for some:

| Task | Operational baseline | Mature labels in demo seed | Class |
|---|---|---|---|
| LEAD_CONVERSION | rules-v1 lead score | NOT_ENOUGH_DATA | MISSING |
| OPPORTUNITY_WIN | stage-weighted probability | NOT_ENOUGH_DATA | PARTIAL labels |
| CLOSE_DATE_SLIPPAGE | deal insight close-slip flag | NOT_ENOUGH_DATA | MISSING |
| CUSTOMER_CHURN | rules-v2 risk | NOT_ENOUGH_DATA | MISSING |
| CUSTOMER_RENEWAL | renewal readiness | NOT_ENOUGH_DATA | MISSING |
| EXPANSION_PROPENSITY | expansion rules-v1 | NOT_ENOUGH_DATA | MISSING |
| PRODUCT_AFFINITY | whitespace propensity | NOT_ENOUGH_DATA | MISSING |
| CUSTOMER_LIFETIME_VALUE | none | NOT_ENOUGH_DATA | MISSING |
| FORECAST_CALIBRATION | forecast snapshot | NOT_ENOUGH_DATA | MISSING |

Demo seed cannot satisfy conservative minimums (200 rows, 40/40 pos/neg, 90 days). That is correct. Do not train.

## Governance and platform

| Item | Class | Notes |
|---|---|---|
| PredictionTask / FeatureSet / LabelDefinition | MISSING | |
| TrainingExample / DatasetVersion / fingerprint | MISSING | |
| Point-in-time correctness | MISSING | Snapshots use `now()` |
| Censoring | MISSING | |
| Tenant-local datasets | MISSING | Default must be TENANT_LOCAL |
| Cross-tenant training | DEFERRED | Requires legal/governance design |
| Experiment / model registry | MISSING | |
| MLflow | DEFERRED | Internal Postgres registry is enough |
| Champion / challenger | MISSING | Rules are de-facto champion |
| Shadow predictions | MISSING | |
| Prediction records | MISSING | |
| Delayed evaluation | MISSING | |
| Promotion / rollback / audit | MISSING | |
| `ml.*` permissions | MISSING | Model cards use `revops.read` |
| Artifact storage under `models/` | MISSING | Object storage exists for knowledge |
| sklearn / XGBoost | MISSING | Optional extra later; not required to finish Batch 7 |
| Readiness UI | MISSING | `/models` shows rules cards only |
| Fake accuracy | DONE | Cards honestly say rules; `last_trained` conceptually null |
| Autopilot uses rules | DONE | Must not change |
| RLS on future ML tables | MISSING | Pattern exists (009/011 FORCE RLS) |
| Playwright parallelism | PARTIAL | `workers: 1` on shared SQLite; Postgres concurrent profile DEFERRED |

## Batch 7 response

Implement versioned tasks, feature sets, labels, immutable point-in-time snapshots, entity field history, reproducible datasets, readiness gates, internal experiment/model registry, shadow predictions, delayed evaluation, governed promote/rollback, honest `/models` readiness UI, and tests. Production ML remains **DEFERRED** until a task is `READY_FOR_EXPERIMENT` and a human promotes a challenger.
