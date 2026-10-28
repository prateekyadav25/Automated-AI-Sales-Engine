# Current Phase

2026-10-28: Permissioned voice handoff is connected to the existing call, approval, meeting, and journey path, and the local application is on Alembic `043`. A qualified lead, a public number, email consent, or a saved task does not authorize a call. The attempt stores the tenant, lead, enquiry, the lead's own operating plan, the frozen product, the assigned owner, that owner's connected Twilio account, the caller identity, the validated recipient, the purpose, and the permission evidence. Permission is recorded separately from execution authorization. The worker does not open a live Twilio client. Fixture calls pass an explicit fake client.

Twilio Programmable Voice Calls API `2010-04-01` is the contract used. Call create has no documented idempotency key, so an unknown result is not posted again. A stored Call SID can be read back. Status callbacks are verified with the connection token and ordered by `SequenceNumber`. Recording, transcription, and a live transfer bridge are not enabled. A completed call is not a useful conversation, a qualification, or a sale. A human request creates one follow-up task. An explicit meeting request creates a proposal that still needs slot selection and booking authorization.

The demonstration remains prepared. Its expiry is unchanged. Historical holds were not released. No live call, recording, message, booking, or spend was made. The next milestone is commercial activation and the close-won lifecycle. Retention, broader social performance, paid activation and reporting, and SEO stay on the roadmap. The sales engine is not finished.

2026-10-28: Google Meet booking is connected to the existing meeting request, approval, and journey path, and the local application was on Alembic `042`. A qualified lead is not a meeting request. A proposed slot and an approved email are not permission to create an event. The booking stores the tenant, lead, enquiry, the lead's own operating plan, the frozen product, the assigned owner, that owner's connected calendar, the attendees, and the purpose. A missing, revoked, ambiguous, or other-tenant calendar blocks the work. The worker does not open a live Google client. Fixture calls pass an explicit fake client.

A slot is a proposal. Availability is rechecked immediately before create. An empty or missing free/busy response is unavailable, not a free calendar. Daylight-saving gaps and ambiguous local times are skipped. The create is stored before the provider call. A repeated job reads the existing event and does not insert another one. A pending or failed Meet conference keeps that event. Reschedule and cancel wait for provider confirmation, and a stale job cannot recreate a cancelled booking. A booking does not record attendance, win a deal, or create revenue. Fixture join links stay separate from a provider join link.

The demonstration remains prepared. Its expiry is unchanged. Historical holds were not released. No live calendar event, invitation, email, or outbound message was created. That section's next milestone was voice handoff. It is the section at the top.

2026-10-28: Paused Meta campaign assembly for the existing website capture form is connected in fixtures, and the local application is on Alembic `041`. A saved proposal stores the operating plan, frozen product context, audience, geography, Facebook feed placement, dates, time zone, proposed budget, copy, headline, call to action, asset, and destination. That budget is not permission to spend. Assembly creates a paused campaign, ad set, creative, and ad through the existing Meta ads client and keeps each returned id before the next object. A campaign shell alone is not complete. LinkedIn assembly, other objectives, and native lead-form campaign creation stay unsupported. A tracking token on the capture link attributes a consented enquiry. A browser-supplied campaign or ad id is ignored. The same person keeps the first touch and a separate later enquiry. Intake uses the existing acknowledgement and does not open an opportunity or a sequence. Activation, daily and monthly caps, sandbox refusal, and the prepared demonstration stay in force. Expiration still blocks external work. The demonstration remains prepared. Its expiry is unchanged. Historical holds were not released. No live campaign, subscription, or credential change was made. Fixture ids are not a live Meta account.

The Marketing API host in this client is `https://graph.facebook.com/v21.0`. That version is the one the ads client already used. A page-posting token and a lead-retrieval token do not prove ad-account permission, image upload, or delivery. Those live checks were not made.

That section's next milestone was Google Meet booking. It is the section at the top. Do not authorize a send, a post, a booking, a call, discovery spend, or ad spend from this note. Commercial activation, retention, broader social performance, and SEO remain on the roadmap in `docs/revenue-os-next-milestones.md`.

2026-10-28: Meta native lead-form ingestion is connected in fixtures, and the local application was on Alembic `040`. A verified Page `leadgen` notification is stored before it is acknowledged. Lead details are retrieved by the existing worker, tested with fake Graph responses. The tenant and operating plan come from a local page-and-form mapping. An unknown or cross-workspace mapping stays in review. A permitted enquiry follows the acknowledgement path and does not enter an outbound sequence. The same provider submission does not create a second lead. A later submission from the same person keeps a separate enquiry and the original first touch. The demonstration remains prepared. Its expiry is unchanged. Historical holds were not released. No Page subscription, form, campaign, or live Graph call was made.

The lead count of 43 was every lead row. The count of 33 is the same table with `deleted_at` empty. Ten rows were soft-deleted together on 2026-10-10. The audit log has no lead-delete action. Those rows were not restored.

Next recommended milestone: paused paid campaign assembly and attribution. Do not authorize a send, a post, a booking, a call, discovery spend, or ad spend as part of that work. LinkedIn Lead Sync, Google lead forms, comments, direct messages, Meet, voice, commercial activation, and SEO remain required and are listed in `docs/revenue-os-next-milestones.md`.

That section's next milestone was paused Meta assembly. It is the section at the top.

2026-10-28: Organic creative production and provider-backed performance read-back are connected in fixtures, and the local application was on Alembic `039`. An operator can prepare a reviewable content calendar for one selected operating plan. A proposal stays separate from an approved creative. One supported image format can store a local preview. Live publishing still requires a public media URL and an authorized scope. LinkedIn share statistics are read through the provider contract and tested with fake HTTP. Missing metrics stay missing. A recommendation is reviewable and does not change copy, cadence, or spend. The demonstration remains prepared. Its expiry is unchanged. Historical holds were not released.

That section's next milestone was native lead-form ingestion. It is the section above.

2026-10-27: Discovery follow-through is connected in fixtures and the local application was on Alembic `038`. A discovery run stores the tenant, the chosen ICP, and the chosen operating plan, then the existing outbox assesses the person. Missing channel permission keeps the lead and opens a task. It does not acknowledge and it does not create a send approval. A permissioned, assessment-eligible fixture reaches one product-aware draft. Sending stays blocked. The demonstration remains prepared. Its expiry is unchanged. Historical holds were not released. Public hosting remains postponed.

That day's next milestone was organic creative production and performance read-back. It is the 2026-10-28 section above.

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
