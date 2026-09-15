# Current Phase

**Phases 0–22 plus Autopilot batches 1–8 and the full-funnel completion slice are in product.**

Batch 8 still proves a **controlled PILOT** tenant — not unrestricted enterprise production. The funnel slice wires tenant credentials into execution, splits voice, adds meeting capture, deepens ads, and closes first-touch attribution.

Honest limits that stay in force:

- Autopilot is event-driven plus a reconcile beat. Enable Autopilot is the operating switch; Run now only accelerates.
- Tenant `ProviderAccount` rows win over deployment defaults. Live mode never falls back to a silent mock. Admin > Integrations credentials now drive ads, voice, and discovery factories.
- Default `EMAIL_PROVIDER=mock` and `CALENDAR_PROVIDER=mock`. Live Gmail/Calendar require Google OAuth and a connected `provider_accounts` row.
- Discovery, ads, and voice use explicit modes. Live + missing creds is `NOT_CONFIGURED`.
- Voice telephony and conversation are independent. `+91` routes to Exotel unless the tenant overrides. Exotel callbacks are routing-token authenticated; Exotel does not HMAC-sign them. India dials require NDNC/DND, TRAI hours, and recording consent.
- Meeting bots may not join until recording consent is approved. Insights are transcript-cited or abstain.
- Ads can create ad sets, creatives, ads, and activate. Audience sync leaves only consented identifiers. CTR/CPC/CPL persist after a live metrics sync.
- Public inbound capture is key-scoped and rate-limited. Authenticated `POST /acquisition/capture` still requires `acquisition.capture`.
- Usage, support, finance, and ERP ingest only through generic signed webhooks.
- Health is `rules-v2`. Only LIVE + fresh components enter the score.
- Mock discovery invents nobody. Mock ads/voice invent no spend, CTR, or transcripts.
- Feature snapshots and outcome labels accumulate. `last_trained` stays null. `ML_ALLOW_CHAMPION` stays false.
- Production refuses demo seed unless `ALLOW_PRODUCTION_SEED=true`. PRODUCTION also requires `TOKEN_ENCRYPTION_KEY`, a public HTTPS `PUBLIC_API_BASE_URL` for provider callbacks, `METRICS_TOKEN` if metrics are exposed, and ClamAV for uploads.

Ready for **controlled PILOT** after `PilotReadinessService.activate()`. Activate provisions tenant rows from deployment secrets when those secrets exist, then fail-closes if critical checks fail.

Next authorized work: live WhatsApp adapter when credentials exist, Gmail Pub/Sub after measured ingest lag, live vendor HTTP, or a single SHADOW experiment only after a task passes the readiness gate.
