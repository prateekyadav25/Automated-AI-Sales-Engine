# 51 — Model governance

## Permissions

| Permission | Use |
|---|---|
| `ml.view` | Readiness, datasets, registry, predictions |
| `ml.dataset.create` | Build datasets |
| `ml.train` | Start training / download artifacts |
| `ml.promote` | Status changes |
| `ml.rollback` | Restore previous champion |

Super Admin, Tenant Admin, and CRO receive mutate rights. CEO receives `ml.view` only. Sales Rep keeps `revops.read` for honest rules cards.

## Promotion

Human action with reason and audit (`who`, `from`, `to`, `why`, metrics, timestamp).

Do not auto-promote on one metric. Leakage-like feature importance should block promotion (manual review).

Rollback restores the previous champion. Old artifacts are never deleted.

## Execution modes

- Rules remain the live champion.
- ML may be `SHADOW` or later `ADVISORY`.
- `ACTIVE` is rejected for non-rules providers in Batch 7.

ML must not send email, dial, spend, change discounts, close opportunities, or change contracts.

## Tenant isolation

Training data is `TENANT_LOCAL`. RLS covers intelligence tables. Cross-tenant / federated models need a separate legal design.

Retention, deletion, and anonymization apply. No tenant/customer IDs on Prometheus labels.

## Audit + observability

Audited: dataset create, train start/finish, register, promote, rollback, prediction mode change.

Counters: `dataset_build_total`, `dataset_build_failure`, `training_jobs_total`, `training_job_failure`, `predictions_total`, `shadow_predictions_total`, `model_evaluation_total`. Labels: `task_key`, `status` only.

## Playwright / CI

Current Playwright uses one worker on shared SQLite. That is not concurrency proof. A future CI profile should use Postgres and isolated state so selected journeys can run in parallel.
