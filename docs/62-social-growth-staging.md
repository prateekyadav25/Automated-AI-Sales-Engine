# Social Growth staging

A staging deployment for Alembic `047` is a separate stack. It does not use the running demonstration database, its containers, or its object storage. Publishing, insight reads, GA4, and ad spend stay off until a person turns one mode on for a named check.

## What the overlay already fixes

`infra/kubernetes/overlays/staging` sets:

- `ENVIRONMENT=staging`
- `SEED_DEMO=false`
- email, discovery, voice, and ads providers to `mock`
- `META_GRAPH_API_VERSION=v26.0`
- `SOCIAL_GROWTH_PUBLISH_MODE=disabled`
- `SOCIAL_GROWTH_INSIGHTS_MODE=disabled`
- `GA4_MODE=disabled`

`ENABLE_SOCIAL_GROWTH` stays off for every workspace until an operator enables it. The base config map records the same disabled defaults. Secrets are not in Git.

## Isolated resources

Create these before the first pod starts. None of them are the local Compose services.

| Piece | Requirement |
|---|---|
| Postgres | A new database. Restore is `pg_restore` of a staging dump, never the demonstration dump, into that database. The migrate Job runs `alembic upgrade head` with `DATABASE_ADMIN_URL`. API and workers use `agrayian_app`. |
| Redis | A new instance. Beat stays at one replica. |
| Object storage | One bucket shared by API and workers, `OBJECT_STORAGE_PROVIDER=s3`. Instagram fetches media from `PUBLIC_API_BASE_URL`, so the bucket cannot be a pod-local disk. |
| TLS | A public `https` name for the API and the web app. `PUBLIC_API_BASE_URL` is that `https` origin. |
| Secrets | `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY` (do not derive token encryption from `SECRET_KEY`), `METRICS_TOKEN` if metrics are scraped, and Meta or Google secrets only when a later check needs them. |
| Images | The API image includes `ffmpeg` and `fonts-dejavu-core`. A card and a Reel rendered in `salesengine-api:latest` passed their quality checks with no network. |

## Schema

Staging starts empty or from a staging backup and migrates to head. Head is Alembic `048`. `047` only adds row-level security policies. `048` adds the acceptance-authorization table and forces the same tenant policy on it. Downgrade is a no-op. Rolling back means restoring the backup taken before the upgrade and starting the previous images. Do not point this migrate Job at the demonstration database.

The demonstration on this machine is Alembic `046`. Its containers were not restarted for this work. Backups under `.local-backups/`, including `agrayian-before-sample-retirement-2026-10-29.dump`, were left in place.

## Monitoring and recovery

- API health is `GET /health`.
- Worker and beat use the existing heartbeat file and Grafana alerts. Beat must stay a single replica so a post is not scheduled twice from two schedulers. A second tick in one database still publishes once, because the external effect key is unique.
- Take a database dump before the migrate Job and on a daily schedule. Restore practice is a new database, `pg_restore`, then start API and workers against that copy.
- An unknown publish result stays unknown until reconciliation or an operator marks it published or not published. Nothing in staging posts while `SOCIAL_GROWTH_PUBLISH_MODE=disabled`.

## Meta and GA4, not connected

Leave these empty until the acceptance checklist says to fill them:

- `META_APP_ID`, `META_APP_SECRET`, Page tokens, Instagram account ids
- GA4 property id and a Google connection with `analytics.readonly`

Do not subscribe a Page, do not call Graph with a real token, and do not turn publish mode on as part of bringing staging up.

## Local isolated Compose

`docker-compose.staging.yml` is a second project, `agrayian-staging`. It does not read `.env`, does not attach to the demonstration volumes, and publishes different ports: Postgres `5436`, Redis `6381`, object storage `9002`, API `8012`, web `3010`.

```
docker compose -p agrayian-staging -f docker-compose.staging.yml up -d --build
```

`SEED_DEMO` is false. Publishing, insights, GA4, and ads modes are disabled. The object-storage bucket is `agrayian-staging`. Official `minio/minio` and `quay.io/minio/minio` images no longer pull anonymously, so this file uses the S3-compatible image `pgsty/silo:RELEASE.2026-10-26T00-00-00Z`. The values in that file are for this machine only. Replace them before any public host, and set `TOKEN_ENCRYPTION_KEY` rather than deriving token encryption from `SECRET_KEY`.

There is no public HTTPS name in this file. `PUBLIC_API_BASE_URL` stays `http://localhost:8012`, so Instagram publishing stays blocked. Logs are the Compose project logs. Health is `GET /health` on the API, plus the Compose health checks.

The in-product checklist is `/growth/acceptance`. A step is live-verified only after a stored authorization and a provider result. See `docs/64-social-growth-release-readiness.md`.
