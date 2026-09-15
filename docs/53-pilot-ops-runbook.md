# 53 — Pilot operations runbook

Controlled PILOT is not unrestricted production. Demo seed tenants stay `DEMO` until an operator with `pilot.activate` passes the readiness gate.

## Start

1. Confirm Alembic head is `013`.
2. Open Admin → Pilot readiness. Required checks must be READY: migrations, authentication, approvals, emergency stop. Email is required only if outbound Autopilot is enabled and the provider is not MOCK.
3. `POST /api/v1/pilot/activate` with `target=PILOT`. Activation fails closed on critical blockers.
4. Leave Autopilot on. Enable Autopilot is the operating switch; Run now only accelerates.

## Pause / resume

- Tenant pause: Autopilot settings `enabled=false` or Pause tenant on Autopilot.
- Channel pause: email / ads / voice / discovery / WhatsApp flags.
- Emergency stop: tenant `emergency_stop` or `GLOBAL_EMERGENCY_STOP`. Existing rows are not deleted.

## Reconnect

- Google: Integrations → Connect Google. Tokens stay encrypted on `provider_accounts`.
- Ads / voice: save encrypted LinkedIn / Meta / Twilio / Vapi rows. Process-env is used only when `allow_deployment_provider_defaults` is true (DEMO default). PILOT/PRODUCTION default false.
- Never LIVE → MOCK.

## Dead letters

Autopilot → dead-letter panel. Retry or cancel. Reconcile Beat looks up uncertain `provider_actions` by idempotency / external id before re-executing.

## Restore

Operator-only: `scripts/backup/backup.sh`, `restore.sh`, `verify_restore.py`. CI concurrency job counts tenants after migrate/seed. No invented RPO.

## Re-run

Event-driven path plus 15-minute reconcile. Duplicate work uses unique keys; `claim_key` returns the existing effect on unique violation.

## Escalate

- Unexpected outreach: emergency stop, then inspect Approvals and traces.
- Worker crash after provider call: reconcile, do not re-send blindly.
- Cross-tenant suspicion: see [docs/54](54-pilot-security.md).

## Tabletop

| Scenario | Expected |
|---|---|
| Email outage | Provider ERROR / RETRYING / DEAD_LETTER. No mock send. |
| Duplicate callback | One inbox event. Unique `(tenant, provider, external_id)`. |
| Failover | Authoritative CRM/workflow rows stay in Postgres. |
| Worker crash | Reconcile confirms or retries; one SENT message. |
| Bad approval | Execute re-checks consent, expiry, opt-out, completed renewal, cancelled campaign. |
| Emergency stop | Discovery, email, voice, spend stop. |
