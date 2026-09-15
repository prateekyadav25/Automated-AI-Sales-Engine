# 57 — Learning-data collection

Batch 8 collects outcomes. It does not train a production model. `ML_MIN_*` gates stay in force.

## Human outcomes

Required, not inferred:

- Close Lost + controlled reason
- Renewed / Churned + churn reason
- Expansion accepted / rejected / minted / won / lost + value if known + product

`record_outcome` / `upsert_outcome` use event time. AI may suggest a reason; a human confirms. Recommendation feedback is not ground truth (`ground_truth: false`).

## Snapshots

Feature snapshots are immutable. Corrections create a new snapshot with `correction_of_id`. Originals stay. Do not UPDATE/DELETE feature payloads.

## Completeness

Outcome completeness = mature labels / eligible entities. Not raw row counts. Models page shows pending, censored, history days, and **NOT READY**. No fake ETA.

## Readiness notify

When a task first becomes `READY_FOR_EXPERIMENT`, the OS writes an audit / in-app notification. It does not train.

Privileged `ml.train` may start **one** SHADOW experiment on a task that actually passes the gate. Demo seed will not pass. All nine tasks remain `DATA_COLLECTION` until that happens.

## Do not

- Generate synthetic wins/losses
- Use demo records as production labels
- Weaken `ML_MIN_*`
- Promote a champion without `ML_ALLOW_CHAMPION` and a real evaluation
