# 37 — Incident Response

## Severity

- **P0** — tenant isolation failure, credential leak, production demo seed, live send while emergency-stopped, data loss
- **P1** — Autopilot cannot execute, Beat missing, dead-letter growth, restore failure
- **P2** — provider degradation, UI polling-only, missing dashboard panel

## Immediate actions

1. Set `GLOBAL_EMERGENCY_STOP=true` or PATCH `/api/v1/autonomy/settings` `{ "emergency_stop": true }`. This suspends new external actions. It does not delete work.
2. Pause the affected channel (`email_channel_paused`, `ads_channel_paused`, `voice_channel_paused`, `discovery_channel_paused`).
3. Disable Autopilot or Pause tenant if the blast radius is the whole workspace.
4. Inspect dead letters on Autopilot (`GET /api/v1/providers/actions?status=DEAD_LETTER`). Retry is idempotent. Cancel leaves the row.
5. Revoke refresh-token families (`POST /api/v1/auth/sessions/revoke-all`) if reuse was detected.

## Evidence

- Correlation IDs on every HTTP response.
- Audit rows for login, refresh reuse, settings changes, approval decisions, provider retries.
- `/metrics` (token-gated in production) and Grafana rules under `infra/grafana/`.
- Provider health on Autopilot and Integrations. `LIVE` without credentials is `NOT_CONFIGURED`, never a silent mock.

## After

Write the timeline, the first-detected signal, and the residual risk in `IMPLEMENTATION_LOG.md`. Rotate leaked secrets. Do not re-enable live providers until staging has reproduced the fix with mock modes.
