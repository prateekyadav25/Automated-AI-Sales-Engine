# 54 — Pilot security

## Credentials

Tenant ads/voice tokens are Fernet-encrypted on `provider_accounts`. Config export never includes tokens. Process-env defaults are allowed only when `allow_deployment_provider_defaults` is true.

## Login and tokens

JWT access + rotating refresh families. Production seed is refused unless `ALLOW_PRODUCTION_SEED=true`.

## Isolation

Every tenant-owned row has `tenant_id`. RLS FORCE policies exist from Alembic 009 onward, including Batch 8 tables. CI `rls` fails if zero tests run. Local pytest still skips without `POSTGRES_RLS_ADMIN_URL`.

## Webhook abuse

Generic signed webhooks remain the production ingest for usage/support/finance. No `X-Tenant-Id` trust. Body size capped.

## Malware

Uploads go to a quarantine key, then scan. Status is `SCANNED_CLEAN`, `SCANNED_BLOCKED`, `NOT_SCANNED`, or `NOT_CONFIGURED`. PILOT may allow unscanned files with an honest label. PRODUCTION blocks upload when the scanner is unavailable (`allow_unscanned_uploads=false`). Blocked files are not retrievable.

## Unexpected outreach

Consent is channel-specific. WhatsApp is never inferred from email or voice. Execute re-checks opt-out, expiry, and stale business state. Emergency stop suspends external actions.

## Tabletop

| Scenario | Expected |
|---|---|
| Cross-tenant read | 404 / empty, not 403 with foreign payload |
| Revoked OAuth | Provider ERROR; no silent mock |
| Malware on upload | Quarantine + BLOCKED; download 404 |
| Token reuse after logout | Refresh family revoked |
| Webhook without signature | 401 / 403 |
