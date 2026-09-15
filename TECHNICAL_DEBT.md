# Technical Debt

- IVFFlat/HNSW indexes are not installed. Add them when knowledge chunk counts leave the small-tenant range. `embedding_json` remains until a Postgres-only cutover is scheduled.
- Object storage defaults to local disk outside Compose. Malware scanning stays `NOT_CONFIGURED` until `MALWARE_SCANNER` is set. ClamAV is optional.
- OpenTelemetry exports only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set and the optional `otel` extra is installed.
- Grafana dashboards reference some gauges that operators must scrape from Celery/Postgres exporters (`up{job="postgres"}`, worker counts).
- Playwright live Gmail/Calendar e2e still needs a connected Google account.
- Product usage, support, finance, and ERP ingest via generic signed webhooks. Labeled mocks remain for demo. Zendesk / Freshdesk / ServiceNow / Stripe HTTP clients stay `NOT_CONFIGURED` until credentials exist.
- Gmail push/Pub/Sub can attach to `provider_inbox_events`; history sync is the working ingest path.
- Ads/voice can now store encrypted tenant `ProviderAccount` rows. Process-env remains the local/dev fallback when policy allows. Live vendor HTTP for ads/voice is still mock or NOT_CONFIGURED without credentials.
- WhatsApp architecture is complete as `NOT_CONFIGURED`. A live adapter is deferred until credentials exist.
- Ads status/metrics are polled (`sync_ad_campaigns`); ads webhooks are not required.
- PagerDuty is out of scope. Aikido stays optional.
- Production must set `TOKEN_ENCRYPTION_KEY` instead of deriving Fernet from `SECRET_KEY`.
- Compose API still runs `alembic upgrade head` for local DX. Kubernetes replicas do not.
- Web UI view-models in `apps/web/src/lib/types.ts` remain; generated OpenAPI paths live in `@agrayian/types`.
- Playwright stays at one worker. E2E-LITE uses SQLite; E2E-POSTGRES is isolated but still `workers: 1` until journey isolation is proven.
- MLflow is not installed. The internal Postgres registry is enough until experiment volume justifies it.
- Opportunity history starts at Batch 7 write-time. Pre-Batch 7 stage/amount/close mutations were overwritten and cannot be reconstructed.
- Cross-tenant anonymized training is deferred pending legal/governance design.
