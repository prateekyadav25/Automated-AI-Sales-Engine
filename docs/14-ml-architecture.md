# ML Architecture

Evolution: rules → statistics → ML → ensemble.

MVP uses deterministic scoring (lead score, KPI math, NBA heuristics). LLMs explain scores; they do not fabricate them.

Phase 21 in this build is **rules-v1 model cards only**. `last_trained` is null. No invented accuracy, drift, or trained win/churn models until labeled history exists.

Phase 21 later adds feature pipelines, training, a model registry, drift monitors, and models for conversion, win probability, forecast, churn, expansion, LTV, and affinity.

Libraries later: scikit-learn, XGBoost, LightGBM, PyTorch. Do not over-engineer MLOps before labeled data exists.
