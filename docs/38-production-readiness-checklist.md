# 38 — Production Readiness Checklist

Evidence is in this repository after Batch 5. Aikido remains optional (`NOT_CONFIGURED` if unsigned-in).

| Criterion | Evidence |
|---|---|
| RLS + omit-predicate regression | Alembic `009`, `set_config` in `tenant_context.py`, `tests/test_rls_postgres.py`, CI `rls` job |
| Refresh-family replay | `RefreshToken` family columns, `auth.refresh_reuse_detected`, `tests/test_auth_sessions.py` |
| pgvector retrieval | Alembic `010`, `rag.py` `<=>` path, JSON fallback, `tests/test_rag.py` |
| Object-stored binaries | `ObjectStorageProvider`, upload/download, `tests/test_object_storage.py` |
| Generated OpenAPI + drift | `scripts/generate_openapi.py`, `packages/types`, CI `openapi` job |
| Restore-tested backups | `scripts/backup/*`, `docs/36-disaster-recovery.md` |
| Dead-letter ops | Autopilot panel pagination + retry/cancel, `reconcile_requested_actions` |
| SecretProvider + no prod demo seed | `providers/secrets.py`, `seed()` refuses production, compose seeds only if `SEED_DEMO=true` |
| OTel / metrics | `telemetry.py` when endpoint set; Prometheus `/metrics`; Grafana JSON + alerts |
| Emergency pause | `emergency_stop` + channel flags + `GLOBAL_EMERGENCY_STOP` |
| Prod images + K8s | non-root Dockerfiles; Kustomize `web`/`api`/`worker`/`beat` + migrate Job |
| CI security baseline | ruff, pytest, RLS, OpenAPI drift, gitleaks, pip-audit, pnpm audit, Bandit, image build |
| Staging cannot outreach prod customers | staging overlay forces mock providers; `SEED_DEMO=false` |
| No open P0 blockers | See `docs/35-production-readiness-gap-analysis.md` closeout and `TECHNICAL_DEBT.md` |
