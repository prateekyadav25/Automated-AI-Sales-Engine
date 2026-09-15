# Full-funnel completion notes

Tenant credentials saved in Admin > Integrations are the execution source of truth. A connected row is LIVE. Live without credentials is NOT_CONFIGURED. Nothing falls back from live to mock.

Exotel is the India telephony primary. Status callbacks hit `/api/v1/webhooks/exotel/{routing_token}`. Exotel does not HMAC-sign those callbacks. Verification is the secret routing token plus an optional `EXOTEL_IP_ALLOWLIST`. That is weaker than Twilio or Vapi signatures.

India outbound dials are blocked unless NDNC/DND is CLEAR, the clock is inside 10:00–21:00 IST on a non-Sunday, and recording/voice consent exists for the announcement.

Meeting bots do not join until recording consent is approved. Meeting intelligence may only cite the transcript.

Public website capture uses a hashed per-tenant form key. The authenticated capture route remains permissioned.

Campaign ROAS is closed-won opportunity amount on `campaign_id` divided by persisted `campaign.spent`.

Local `.env` now has a dedicated `TOKEN_ENCRYPTION_KEY`, `METRICS_TOKEN`, ClamAV settings, and `PUBLIC_API_BASE_URL`. PRODUCTION activate still fail-closes until that URL is public HTTPS, ClamAV is actually reachable, and Aikido is signed in for the workspace scan. ML tasks keep accumulating labels. No champion is forced.
