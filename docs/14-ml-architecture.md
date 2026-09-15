# ML Architecture

Evolution: rules → statistics → ML → ensemble.

Production scoring remains deterministic (`rules-v1` / `rules-v2`). LLMs explain scores; they do not fabricate them.

Batch 7 adds the trustworthy-learning foundation: versioned prediction tasks, point-in-time feature snapshots, versioned labels with censoring, reproducible tenant-local datasets, readiness gates, an internal experiment/model registry, shadow predictions, delayed evaluation, and governed promote/rollback.

No production ML model is required to complete this foundation. Tasks stay `DATA_COLLECTION` until minimums are met. Experimental models, if ever trained, start as `SHADOW` only.

See docs 45–51 and ADRs 023–028.

Libraries later: scikit-learn (optional extra), then XGBoost / LightGBM. Do not start with deep networks without evidence.
