# 50 — Model evaluation

No experimental model may silently influence Autopilot.

## Statistical metrics (defined, not fabricated)

Classification: ROC-AUC, PR-AUC, precision, recall, F1, Brier, calibration.

Ranking: NDCG, Precision@K, Recall@K.

Regression: MAE, RMSE, MAPE where appropriate.

Survival: concordance index where relevant.

Do not optimize only accuracy. Revenue classes are often imbalanced — always publish class counts beside accuracy.

## Business metrics

Top-K lift, conversion lift, revenue capture, false-positive workload, human review burden.

## Calibration

If opportunities are predicted at 70%, they should win about 70% over time. Track Brier score. Calibration curves can be added later; the schema is ready.

## Delayed labels

`ml_evaluate_matured` (daily) joins `Prediction` to a matured label and writes `ModelEvaluation`. It never promotes.

## Shadow comparison

For an eligible task the platform can store: rules prediction, challenger prediction, later outcome.

Challenger `execution_mode` is `SHADOW`. Autopilot, dispatcher, email, voice, discounts, and close paths do not read these rows.

## Drift foundation

`feature_drift_baselines` stores training-time distributions (mean/median/missingness/categorical). Production comparison is later work.

## Explainability

`top_features_json` / `importance_json` exist for later SHAP-style work. Do not expose raw SHAP without interpretation. Do not let an LLM invent reasons that contradict the features used.
