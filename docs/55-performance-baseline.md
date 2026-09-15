# 55 — Performance baseline

This page publishes **measured** values only. Do not invent 10k/100k numbers.

## How to measure

```
python scripts/pilot_load.py --n 25
```

CI may run a small N. A local operator can raise `--n`. Record Autopilot reconcile, Home, Approvals, Customer 360, webhook ingest, and SSE timings from the script output.

## Current measured values

No production load run has been published in this repository as of Batch 8. Until an operator pastes EXPLAIN ANALYZE and script output here, treat capacity as unknown.

Do not add HNSW “because pgvector exists.” Document measured chunk-count / latency first.

## Worker topology

Keep one worker `-Q` list unless a measured queue is hot. Do not split `ai` / `maintenance` deployments without a hotspot.

## Autoscaling notes

Kubernetes overlays exist. Autoscaling notes belong here only after a measured run.
