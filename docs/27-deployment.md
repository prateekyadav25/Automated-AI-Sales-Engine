# Deployment

Local: `cp .env.example .env && docker compose up --build`

Services: postgres (pgvector), redis, minio, api, worker, web.

Production target: Kubernetes. `infra/kubernetes` holds stubs only in MVP. GitHub Actions should lint, typecheck, test, build images.

Do not require cloud credentials for local development.
