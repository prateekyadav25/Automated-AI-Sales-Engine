# 49 — Experiment and model registry

Internal Postgres registry. MLflow is optional later and is not required.

## ModelExperiment

Tracks algorithm, hyperparameters, code version, times, status, metrics, artifact reference. Metrics are stored only when computed. Empty metrics stay empty.

## ModelVersion

Statuses: `EXPERIMENTAL` → `CANDIDATE` → `CHALLENGER` → `CHAMPION` → `RETIRED`.

Rules-v1 / rules-v2 are seeded as `CHAMPION` (`is_rules=1`). Future ML starts as `EXPERIMENTAL` or `CHALLENGER`.

Batch 7 refuses promoting a non-rules model to `CHAMPION` unless `ML_ALLOW_CHAMPION=true`.

## Lineage

Model → experiment → dataset → training examples → feature snapshots → operational sources.

Reproducibility fields: Python version, package versions, git commit, feature/label/dataset versions, dataset fingerprint, random seed.

## Artifacts

Stored via `ObjectStorageProvider` at `tenant/{tenant_id}/models/{task_key}/{version}/artifact`.

Download requires `ml.train` (or promote). `ml.view` cannot fetch raw artifacts.

## Training jobs

Celery tasks `ml_build_dataset`, `ml_train_candidate`, `ml_evaluate_candidate` exist and refuse unless the readiness gate passes.

CLI: `python -m app.ml readiness|build-dataset|train|evaluate|promote`.

Optional extra: `pip install -e ".[ml]"` for scikit-learn. No GPU cluster. First algorithms, when authorized: logistic regression, then gradient boosting.
