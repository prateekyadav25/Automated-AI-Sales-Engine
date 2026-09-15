# Kubernetes

Kustomize base lives in `infra/kubernetes/base`. Overlays:

- `overlays/staging` — all outreach providers forced to mock; no demo seed
- `overlays/production` — `ENVIRONMENT=production`, `SEED_DEMO=false`

Workloads: `web`, `api`, `worker`, `beat` (replicas=1). Schema changes go through the `agrayian-migrate` Job using `DATABASE_ADMIN_URL`. API and worker pods assume the schema is current.

Postgres, Redis, and object storage are external. Secrets are not in Git.

What scales horizontally: API and web. Workers can scale. Beat must stay at one replica.
