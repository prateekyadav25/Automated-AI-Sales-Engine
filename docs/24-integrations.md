# Integrations

Never place external SDK logic inside domain services.

```text
EmailProvider
  MockEmailProvider
  GmailProvider
  OutlookProvider
```

Same pattern for advertising, voice, calendar, CRM, support, finance, product usage, company/contact/intent data.

Post-sale providers: `MockProductUsageProvider` is always labeled MOCK and is excluded from the health total. `UnavailableSupportProvider` and `UnavailableFinanceProvider` return NOT_CONFIGURED. They are not silent zeros.

MVP: mock email, mock calendar, mock company/contact data. Live adapters are added when credentials exist and must implement the same interface plus an integration health check.

## Gmail and Google Calendar (batch 2)

Env: `EMAIL_PROVIDER=mock|gmail`, `CALENDAR_PROVIDER=mock|google`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `TOKEN_ENCRYPTION_KEY`.

Connect from `/admin/integrations`. One Google row per tenant user. Scopes are stored; Gmail and Calendar health are shown separately.

Send path: Approval → ActionDispatcher → EmailProvider. Status is PENDING/SENDING/SENT/FAILED/RETRYING. Live + disconnected = Blocked by configuration.

Inbound: Celery `sync_inbound_mail` (60s) reads Gmail history into `provider_inbox_events`, then `email_messages`. `POST /api/v1/webhooks/{provider}` persists first (HMAC `X-Webhook-Signature`). Mock inject: `POST /api/v1/integrations/inbox/simulate`.

Idempotency: `email.send:{tenant}:{approval_id}` and unique `(tenant_id, provider, provider_message_id)`.

## Live discovery, ads, and voice (batch 4)

Process-level env (not per-tenant OAuth):

- `DISCOVERY_PROVIDER=mock|apify` plus `APIFY_API_TOKEN`, `APIFY_ACTOR_ID`, `APIFY_LINKEDIN_PROCESS_TOKEN`
- `LINKEDIN_ADS_MODE=mock|live` plus `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_AD_ACCOUNT_ID`
- `META_ADS_MODE=mock|live` plus `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`
- `VOICE_PROVIDER=mock|twilio|vapi` plus Twilio/Vapi vars (`VAPI_ASSISTANT_ID`, `VAPI_PHONE_NUMBER_ID`, `VAPI_WEBHOOK_SECRET`)

Live mode without credentials is `NOT_CONFIGURED`. Live HTTP failure never swaps to mock.

`POST /api/v1/webhooks/{provider}` authenticates (HMAC, Twilio signature, or Vapi secret), persists `provider_inbox_events`, returns 200, then processes on Celery (inline on SQLite tests). Ads status/metrics sync via `sync_ad_campaigns` every 5 minutes.

Idempotency: `ads.launch:{tenant}:{approval_id}`, `voice.dial:{tenant}:{approval_id}`. Trace and dead letters live in `provider_actions`.
