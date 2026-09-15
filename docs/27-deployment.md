# Deployment

Local: `cp .env.example .env && docker compose up --build`

Services: postgres (pgvector), redis, minio, api, worker, web.

Production target: Kubernetes via `infra/kubernetes/base` and `overlays/staging|production`. GitHub Actions lint, typecheck, test, prove OpenAPI drift and RLS, and build images. Staging overlays force mock outreach providers.

Do not require cloud credentials for local development.
