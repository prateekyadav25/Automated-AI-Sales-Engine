# Revenue OS next milestones

This plan follows the audit in `docs/current-capability-audit.md`. It connects the modules that already exist. It does not add a second orchestrator, replace Gemini, or lift the local-only deployment.

The running demonstration stays `prepared`. None of these milestones authorize a send, a post, a call, a booking, or ad spend. Live provider checks are a separate evidence step after the fixture journey is green.

## Status on 2026-10-28

**Organic creative production and provider-backed performance read-back are complete as a fixture path, and the local application is on Alembic `039`.** Discovery follow-through, outbound drafting, and organic acquisition remain complete as fixture paths. The next milestone to implement is native lead-form and supported enquiry ingestion. Paid campaign children, Meet, voice, commercial activation, and SEO remain required and are not started by this slice.

The calendar, the local preview, the LinkedIn statistics adapter, and the reviewable recommendation are fixture-tested. A live metrics request was not made. The prepared demonstration was not authorized and its expiry was not changed.

## Status on 2026-10-27

**Discovery and enrichment follow-through is complete as a fixture path, and the local application was running that code at Alembic `038`.** Outbound drafting and organic acquisition from earlier the same day remain complete as fixture paths. The milestone after that status was organic creative production and performance read-back. Milestone 2's paused campaign children were not built. Only the spend fail-closed gate from that milestone was pulled forward. Milestone 4 no longer means "put the GOV price in every email." The price stays in the frozen context and is written only when the step or the enquiry asks.

What is now connected, in fixtures:

- Approved creative, a due schedule, the scheduler task `publish_due_operating_plans`, one mock publication, a capture submission, the lead and journey, and one product-aware acknowledgement.
- One product context, built from the company profile, the selected catalogue row, and the operating plan's frozen snapshot. The creative stores that context. The acknowledgement uses the context frozen on the creative that the enquiry came from.
- A publication token on the creative and on the stored post link. Capture accepts that token only when it belongs to the same tenant. A plan-level UTM string does not attribute the lead by itself.
- Billable discovery on every `DEMO` tenant. A missing scope, a prepared scope, or an authorized scope without `discovery.search` does not call the provider. `PILOT` and `PRODUCTION` keep their previous path. Mock and unconfigured discovery stay available.
- Paid activation. Zero, missing, invalid, or exhausted daily or monthly limits refuse activation. Zero means no authorized spend. The Meta sandbox refusal remains after that check.

What the organic milestone did not do:

- It did not create ad sets, creatives, or ads, and it did not activate a campaign.
- It did not publish, send, book, call, or spend against a real provider.
- It did not authorize the prepared demonstration or change its expiry.
- It did not personalise outbound email. The acknowledgement quotes the enquiry and the stored product. It does not invent company research.

The outbound milestone, later the same day, closed that last item in fixtures. Its files and checks are below.

### Files changed

- `apps/api/app/services/product_context.py` — shared context.
- `apps/api/app/services/marketing.py`, `content.py`, `acknowledgement.py`, `acquisition.py`, `social.py` — draft, schedule, publish, capture, and the post link.
- `apps/api/app/services/demo_guard.py`, `discovery.py`, `autonomy.py` — DEMO discovery gate.
- `apps/api/app/services/ads.py` — spend fail-closed.
- `apps/api/app/models/operating_plan.py`, `crm.py`, `acquisition.py`, `apps/api/app/schemas/acquisition.py`, `apps/api/app/api/v1/public.py`, `apps/api/alembic/versions/036_publication_attribution.py` — publication token, frozen context, and lead attribution.
- `apps/api/app/workers/celery_app.py` — due-publish beat.
- `apps/api/tests/test_organic_acquisition.py`, `test_ads.py`, `test_demo_readiness.py`.
- `apps/web/src/components/command-operations.tsx` — existing plan view.
- `docs/current-capability-audit.md`, this file, `IMPLEMENTATION_LOG.md`, `CURRENT_PHASE.md`.

### Checks

- `py -m pytest tests/test_organic_acquisition.py tests/test_ads.py tests/test_content.py` plus the combined-offer and prepared-acknowledgement tests: 28 passed.
- `py -m pytest tests/test_organic_acquisition.py::test_due_schedule_attributes_one_mock_publication_and_prepares_one_reply tests/test_social_posts.py`: 20 passed.
- `ruff check` on the changed Python files: clean.
- `npm run typecheck` in `apps/web`: clean.
- Local images for api, worker, beat, and web were rebuilt. The database is Alembic `036`. The demonstration scope is still `prepared`, with the same expiry. Creative versions are still drafts. Social posts, outbound email, and provider actions did not increase.
- The command centre and the revenue-journey page show Autonomous Revenue OS, internal SKU GOV, the stored drafts as not sent, zero attributed enquiries, and acknowledgement counts. No publish, research, or send button was used.

### Fixture evidence and real-provider evidence

Fixture evidence is the tests above. They use SQLite and an explicit mock publisher. A live LinkedIn, Meta, Gmail, calendar, or ads call was not made. Historical posts and emails already in the local database are not evidence for this path. Mock publication rows stay `is_mock` with an empty provider id, so they are not verified live posts.

### Outbound files and checks

- `apps/api/app/services/outbound_draft.py` — product binding, research selection, and the sequence draft.
- `apps/api/app/services/content.py` — `draft_email_from_facts` now shares `complete_email_draft` with the fallback.
- `apps/api/app/services/lifecycle.py`, `journey_engine.py`, `orchestrator.py`, `assessment.py`, `qualification.py`, `approval_view.py`.
- `apps/api/app/services/demo_guard.py`, `social.py`, `marketing.py` — DEMO live `social.publish` requires an authorized scope.
- `apps/api/app/models/lifecycle.py`, `assessment.py`, `apps/api/app/schemas/ai.py`, `lifecycle.py`, `apps/api/alembic/versions/037_outbound_product_binding.py`.
- `apps/api/tests/test_outbound_sequence.py`, `test_demo_publish.py`.
- `apps/web/src/app/(app)/automation/approvals/page.tsx`, `apps/web/src/app/(app)/sequences/[id]/page.tsx`, `apps/web/src/lib/types.ts`.

Checks:

- `py -m pytest tests/test_demo_publish.py tests/test_outbound_sequence.py tests/test_social_posts.py::test_extra_links_stay_beside_the_form_and_are_written_into_the_text`: 7 passed.
- Compatibility: lifecycle enrollment, consented intake, the missing-grant block, assessment, organic acquisition, and demo readiness: 35 passed. Ads, content, and social posts were re-run after the live-publisher check was limited to the LinkedIn and Meta classes.
- `ruff check` on the changed Python files: clean. `npm run typecheck` in `apps/web`: clean.
- Alembic `037` was applied to the local database later the same day, with `038`. The approval card, including the context version, was opened in the browser on an isolated fixture. That fixture was deleted. Real approvals were not decided.

### Discovery files and checks

- `apps/api/app/services/discovery.py` — plan and ICP binding, recorded filters, deduplication, and the lead-page fields.
- `apps/api/app/services/orchestrator.py` — discovery intake, the permission task, and the refusal to simulate research.
- `apps/api/app/services/enrichment.py` — discovery calls enrichment without simulated firmographics.
- `apps/api/app/services/assessment.py`, `journey_engine.py`, `marketing.py`.
- `apps/api/app/models/crm.py`, `apps/api/alembic/versions/038_discovery_icp_binding.py`.
- `apps/api/tests/test_discovery_follow.py`.
- `apps/web/src/app/(app)/leads/[id]/page.tsx`, `apps/web/src/components/command-operations.tsx`, and the approval context version.

Checks:

- `py -m pytest tests/test_discovery_follow.py tests/test_acquisition_marketing.py::test_discovery_ranks_without_consent_and_collapses_duplicates tests/test_outbound_sequence.py tests/test_demo_publish.py`: 10 passed.
- `ruff check` on the changed Python files: clean. The web image build completed, which typechecks the approval and lead pages.
- Disposable Postgres: a restored copy of the `036` backup upgraded to `038` and kept 9 enrollments, 18 approvals, 43 leads, and 901 decisions. Existing context was blank, `outbound_eligible` stayed false, and `icp_id` stayed null. The prepared scope and its expiry were unchanged. The copy was dropped, then the same upgrade was applied to the local database.
- Browser: the isolated approval showed Autonomous Revenue OS, deterministic generation, context version `product-context-v1`, the company fact, the labeled inference, and the missing email, phone, and research. The isolated lead showed discovery source, the bound plan's customer-facing product, enrichment not started, the missing firmographics, channel permission missing, the consent task sentence, and that approval id. Both rows were deleted.

### Remaining gaps

- A live Apify search, a live enrichment vendor, and a live model were not used. The discovery path records unsupported research instead of inventing it.
- Paused paid campaign children are not built. The spend gate is.
- Meet is unchanged.
- A DEMO tenant with no demonstration scope cannot run billable discovery, and it cannot call the LinkedIn or Meta publisher. A mock publisher remains available. Nothing is currently due. The prepared demonstration was not authorized.
- A public host, MinIO, and a live publish authorization are still required before a real post.

## Why this order

Customer-visible value is an enquiry that names the right offer and lands in the sales journey the product already runs. Milestone 1 connects the operating plan, the due schedule, the mock publication, the capture form, and the acknowledgement through one frozen product context. Milestone 4 now uses that same context for every sequence step. Paid campaign children still do not.

Later paid work should reuse the same capture and the same offer text. Building a new campaign structure before the form remembers where the person came from would create another disconnected button.

Gemini stays the configured model. A sequence draft now receives the step, the frozen product, the lead, and eligible stored research. On failure it stores a labeled fallback instead of the template. The acknowledgement still does not call the model. Discovery can now store a person and carry the selected product into that draft. It still does not call Apify during the fixture proof, and it does not invent research when the model is mock or unconfigured.

## What to reuse

| Already built | Reuse it for |
|---|---|
| `OperatingPlan.context_snapshot` and SKU `GOV` | The only offer text the new journeys may quote |
| `acknowledgement.prepare_acknowledgement` | The sales response to a form lead |
| `capture_inbound`, public forms, UTM fields | The only automated lead source in these milestones |
| `LinkedInSocialPublisher`, `MetaSocialPublisher`, `publish_scheduled` | Organic publish, behind the existing demo block |
| `execute_ads_spend`, `create_ad_set`, `create_creative`, `create_ad` | A paused campaign shell plus the missing children, still not activated |
| `orchestrator.handle_event` for `lead.created` | The handoff into sales. Do not add a marketing orchestrator |
| `demo_guard.external_execution_block` and grants | Keep sequence, ads, and voice outside the demonstration |
| `draft_email_from_facts` | Outbound copy, after it is given the snapshot and the lead |
| `GoogleCalendarProvider.create_event` | Meet, by extending this payload rather than a second calendar client |
| `close_won` / `activate_customer` | Leave them as the won path. Do not wire quote acceptance into them |

## Milestone 1 — Product-aware organic acquisition with attributed inbound continuation

**Complete in fixtures on 2026-10-27.** The original draft of this milestone always printed the setup price. The implemented rule is narrower: the creative carries the selected product's price, and the acknowledgement includes that price only when the enquiry asks about it.

A scheduled operating-plan creative for the selected product publishes through the existing publisher when its time arrives. The form on that post creates one consented lead that remembers the publication, the plan, and the product snapshot. Intake queues the existing acknowledgement. That acknowledgement names the customer-facing product and quotes the enquiry. It does not import another SKU.

### Acceptance journey

1. A fixture tenant has the `GOV` snapshot: name, one-time price INR 300,000, and a description. `CORE` and `CS` exist and must not appear.
2. The creative is authorized in the fixture and given `scheduled_for` in the past. A beat task calls the existing `publish_scheduled`. The publisher is the mock. No HTTP client is constructed.
3. The stored post is a mock publication: `is_mock` true, empty provider id, and outcome `mock`. Its link is the capture form plus the publication token. The token is not a provider post id.
4. A form submission with name, email, a short request, email consent, and that token creates one lead. The lead stores the creative, the post, and the plan. Repeating the same email does not create a second lead or a second acknowledgement. A token from another tenant is ignored.
5. A submission missing the request note or consent stays on the existing hold path and does not start intake.
6. `lead.created` runs `prepare_acknowledgement`. The approval confirms receipt, names Autonomous Revenue OS, and quotes the note. A note that does not ask about price does not contain `300,000`, `50,000`, or `400,000`. A note that asks the setup price contains `INR 300,000` for companies under 200 employees and no other SKU price. The internal SKU is not the customer-facing name.
7. A consented enquiry with no title and no company still receives that acknowledgement. It does not become sales-qualified and it does not create an opportunity.
8. The prepared demonstration still blocks `execute_email_send` and the live publisher. The test asserts the block string and no outbound message.
9. Gemini is not required. The operating-plan body comes from the stored context, and the acknowledgement stays deterministic.
10. A future `scheduled_for` does not publish. A second scheduler pass does not create a second post. A mock post has an empty provider id and is labeled mock, not a verified live post. Reconcile of an unknown effect still confirms a real provider id without a second call.

### Engineering

Done. The scheduler task calls `marketing.publish_scheduled` with `only_due=True`. No second publisher was added. `leads` and `inbound_captures` store the creative, the plan, and the post. The creative stores `publication_token` and `context_json`. Alembic `036` adds those columns. The acknowledgement reads the frozen context, quotes the note, asks the remaining firmographic questions, and skips the business-need question when the note already states it. Price is included only when the note asks. A missing form still blocks publish. This lead is not enrolled in a sequence.

### Configuration

None for the fixture. Live proof is a later check and needs the inputs at the end of this document. The fixture journey passes before any public host exists. The running containers serve this code only after the local images that contain it are the ones that are up.

### Completion evidence

- `apps/api/tests/test_organic_acquisition.py` uses the mock publisher and does not construct a live HTTP client. It does not sync a mailbox and it does not run Apify.
- The creative and the price-asking acknowledgement fail if another SKU's price appears. The non-price acknowledgement fails if it contains the setup amount. The prepared-scope test still finds no outbound message.
- The prepared demonstration scope is not authorized by these tests.
- `IMPLEMENTATION_LOG.md` names the test and states that nothing was published or sent.

### Real-provider check, deferred

After the fixture is green, and only with explicit authorization: one LinkedIn, Facebook, or Instagram publish to a test destination, then one form submission, then one acknowledgement. Record the provider id and the lead id. Do not treat an old permalink in the database as this check. LinkedIn's last recorded permission read was HTTP 403, so Instagram or Facebook is the safer first live network if their tokens still post. That choice is user input, not an assumption.

## Milestone 2 — One paused paid campaign becomes the same enquiry

Not started, except for the spend gate below. Build the campaign children the launch path currently skips, point them at the same form, and prove a submission is attributed. Activation and spend stay refused.

The fail-closed spend check is already in `budget_block_reason`. A daily or monthly limit that is zero, missing, invalid, or exhausted returns `No ad spend is authorized. A zero, missing, or invalid limit cannot activate a campaign.` or the exhausted-limit string. That does not assemble an ad set, a creative, or an ad.

### Acceptance journey

1. The fixture creates a LinkedIn or Meta campaign in the provider fake as paused, with an ad set, a text creative, and an ad. The destination is the Milestone 1 form and includes the campaign id and ad id.
2. `execute_ads_spend` is not the success path of this test. The test calls the creative functions and asserts the campaign status stays draft or paused.
3. A form submission creates one consented lead with `campaign_id` and `ad_id` set. Intake queues the same `GOV` acknowledgement as Milestone 1.
4. The Meta sandbox refusal and the prepared-demo block both remain. A test that sets `LINKEDIN_ADS_MODE` to live still cannot confirm an activation while the scope is `prepared`.
5. A zero, missing, or invalid daily or monthly limit already refuses activation. That check is done. The rest of this journey, including the paused campaign children, is not.
6. No metric is invented. Sync of an unsynced campaign returns the provider's empty result.

### Engineering

- Still to do: call the existing `create_ad_set`, `create_creative`, and `create_ad` from the campaign assembly path before any activate call. Keep activate behind the current approval and the demo guard.
- Done: activation fails closed when either the daily or the monthly limit is zero, missing, invalid, or exhausted.
- Stamp ad identifiers onto the capture the form already supports.
- Leave `campaign.launched` as an event. `lead.created` remains the sales trigger.

### Configuration

Set Meta to sandbox for any local live HTTP experiment. Leave activation unauthorized. Do not switch LinkedIn ads away from `live` until the user asks; the new fail-closed cap must make `live` plus a zero limit refuse activation even after the demonstration is later authorized.

### Completion evidence

- Fixture test: paused structure, attributed lead, acknowledgement names `GOV`, no `CONFIRMED` ads action, no spend decimal written.
- Done: zero, missing, invalid, and exhausted limits refuse activation with a stable error string. The paused campaign structure and its attributed lead are still open.
- Real-provider evidence is explicitly out of this milestone. Sandbox campaign create, if the user later allows one HTTP call, is recorded as sandbox and is not spend.

## Milestone 3 — The existing booking stores a Meet link

Extend `GoogleCalendarProvider.create_event`. Do not add a second calendar integration.

### Acceptance journey

1. A fixture meeting proposal already has a chosen slot.
2. The Google client fake receives a create payload with `conferenceData.createRequest`.
3. A successful response with a Meet URL stores that URL on the meeting row and returns it to the approval detail.
4. A successful event with conference status pending stores the event id and a pending conference state. It does not invent a `meet.google.com` URL.
5. A failed create stores no URL and does not mark the meeting booked.
6. The prepared demo still blocks `calendar.book`, so the fixture calls the provider function directly with the fake HTTP client.
7. Recall and transcription stay as they are. The stored URL is available for a person to pass to capture. This milestone does not join the meeting.

### Engineering

- Add the conference request on the existing insert, and send `conferenceDataVersion=1`. Without that query parameter Google accepts the event and drops the conference.
- Read `hangoutLink` or the conference entry point from the response. Add a field on `MeetingRecord` for the join URL and the conference state.
- Re-check busy time inside `book_meeting` before create, using the existing `get_availability` result. A conflict returns a booking error and does not create a second event.

### Configuration

None for the fixture. A live create still waits for an authorized `calendar.book` and the connected Google account. The account already has `calendar.events`. That scope includes the permission Google requires for conference creation; if a live call later rejects the conference request, record the status and stop. Do not book a real meeting during implementation.

### Completion evidence

- Fake HTTP tests for created, pending, and failed conference data.
- No row with provider `google` is required in the local database until the user authorizes one booking.

## Milestone 4 — Product-aware, evidence-based outbound drafting

**Complete in fixtures on 2026-10-27.** The sequence reuses `draft_email_from_facts` and the shared product context. It does not send.

### Acceptance journey

1. Two consented leads with different roles, companies, and enquiries receive different drafts. Each draft connects a stored benefit to that lead's facts and does not contain the other lead's company.
2. With two products and two plans present, the sequence's operating plan selects one product. The other SKU's name and price do not appear.
3. Research from another tenant, another account, or older than 30 days is excluded. Research with a source for the same account is included as a sourced observation. An inference is labeled as not a verified problem. Missing research produces a shorter honest draft.
4. A model failure stores a labeled deterministic draft. The body has no unresolved placeholder and does not copy an unsupported discount or testimonial from the template. A fixture model response is stored as `generation: model`.
5. The second sequence step uses the context frozen at enrollment. Changing the catalogue price and the plan snapshot does not change the approved draft or that next step.
6. A lead with score 10, consent, a company, and an explicit outbound assessment is enrolled. A lead with score 95, consent, and no company or firmographic facet is not enrolled and does not get an acknowledgement. An unconsented discovery lead gets neither. A public-form enquiry stays on the acknowledgement and is not enrolled. Repeating enrollment or the due step does not create a second approval for the same step.
7. A prepared scope makes zero calls to the email provider. A DEMO tenant without an applicable authorized scope makes zero calls to the LinkedIn or Meta publisher, from both the direct publish path and the scheduler. A mock publisher still runs. An authorized fixture scope for that version and channel can reach a stub once.
8. The approval card shows the product, subject, body, facts, references, missing information, generation, eligibility, and next action.

### Engineering

Done. `complete_email_draft` is the same function path as `draft_email_from_facts`. `outbound_draft.prepare_sequence_draft` builds the facts and the fallback. `sequences.operating_plan_id`, `sequence_enrollments.context_json`, and `assessment_decisions.outbound_eligible` are in Alembic `037`. No second orchestrator was added.

### Configuration

None. The prepared demonstration was not authorized and its expiry was not changed.

### Completion evidence

- `apps/api/tests/test_outbound_sequence.py` and `apps/api/tests/test_demo_publish.py`.
- No live send, publish, booking, call, spend, or discovery.

## Milestone 5 — Close-won remains the customer door

Do this after the acquisition milestones. It is smaller than it looks because `close_won` already creates the customer.

### Acceptance journey

1. An approved quote can be accepted and stays a quote. The opportunity stage is unchanged.
2. A person runs close-won. The customer, contract line, and onboarding task reference the quoted product SKU.
3. `expansion.detected` still does not open an opportunity by itself. The existing approval-gated expansion path is unchanged.
4. No customer email is sent in the test.

### Engineering

- Surface the accepted quote on the close-won confirmation so the operator sees the product and the total. Keep the two actions separate.
- Copy the quote's product id onto the activation inputs the service already accepts. Do not invent a second onboarding engine.

### Completion evidence

- Fixture: accept then close-won yields one customer and one onboarding task for that SKU. Accept alone yields neither.

## Configuration versus engineering

| Work | Engineering now | Configuration later, not required to finish the fixture |
|---|---|---|
| Milestone 1 | Done in fixtures: scheduler call, publication token, frozen product context, acknowledgement that quotes the enquiry | A public HTTPS media URL if the live post is Instagram. A still-valid page token. Explicit publish authorization. The local containers must be running the image that contains this code |
| Milestone 2 | Spend limits already fail closed. Still to build: campaign children and paid attribution | A non-zero budget cap before any real activation. Meta stays sandbox. LinkedIn activation stays unauthorized |
| Milestone 3 | Conference payload, stored URL, second busy check | One authorized Google event create |
| Milestone 4 | Done in fixtures: bound product, evidence-labeled drafts, assessment eligibility, DEMO live-publish gate. Alembic `037` is applied locally | None until someone authorizes a sequence or a publish, which this plan does not do |
| Discovery follow-through | Done in fixtures and running locally at Alembic `038`. Missing enrichment stays incomplete | A live discovery provider, which this plan does not call |
| Milestone 5 | Show the accepted quote on close-won | None |
| Public host | Not a code prerequisite | Compose ports, Postgres volume, Google redirect URI, CORS, web origin, `PUBLIC_API_BASE_URL` on HTTPS |
| MinIO | Not required for mock publish | Required before Instagram can fetch a generated image. It is defined in compose and is currently stopped |
| Gmail | Keep polling | Pub/Sub is deferred. Inbound already works without a public callback |
| Voice and Meet join | Not in these milestones | Public HTTPS callbacks for Twilio, Exotel, Vapi, and Recall |

## Minimum user input

Collected once. Implementation of the fixture journeys can start without these answers. Live checks cannot.

1. Confirm `GOV` at INR 300,000 remains the only offer these journeys may name. `CORE` and `CS` stay in the catalogue and out of the copy.
2. Choose the first live organic network after Milestone 1's fixture is green. Instagram and Facebook have historical posts in this database. LinkedIn's last recorded organization permission read was HTTP 403.
3. When a public host is wanted, supply the HTTPS API origin, the web origin, the Google OAuth redirect, and CORS origins. Name the host. Do not treat `https://agrayianailabs.com` as this application; the implementation log records it as a separate marketing site.
4. Say whether MinIO should be started for local media, or whether live images will be uploaded to an already public URL.
5. Set a daily and a monthly ad budget cap before any paid activation. Until those numbers exist, activation must keep failing closed.
6. Authorize a specific action before any live publish, acknowledgement, booking, or campaign create. The prepared scope is the current stop. This plan does not authorize it.
7. The second DEMO tenant no longer has an open billable-discovery path. A missing scope blocks that call. Confirm, before any later authorization, that this tenant should stay without a discovery scope. Do not add `discovery.search` unless that spend is intended.
8. For a later live Meet, confirm one mailbox and one slot. Do not provide that during fixture work.

No other credentials are required. Gemini, Gmail, Google Calendar, Apify, and the organic tokens are already present. They must not be exercised by the fixture tests.

## Future milestones

Discovery follow-through is done in fixtures. The journeys below are not. Each one keeps its acceptance so it stays visible.

### Discovery and enrichment follow-through

**Complete in fixtures on 2026-10-27, and running locally at Alembic `038`.** A real provider was not called.

Acceptance that was proved with fixture providers: a sparse person is stored and assessed; missing permission creates a task and no acknowledgement or send approval; a permissioned, eligible person reaches one product-aware draft; a replay does not duplicate the lead, task, enrollment, or approval; another tenant's research is excluded; missing enrichment stays incomplete; a high score without fit does not override the assessment; missing, prepared, expired, and wrong-action DEMO scopes make no live discovery call; a later research note does not rewrite the stored draft.

### Complete organic planning, creative production, and performance read-back

**Complete in fixtures on 2026-10-28, and running locally at Alembic `039`.** A live LinkedIn statistics call was not made. Facebook and Instagram insights remain unsupported by this adapter. Video generation remains unsupported.

Acceptance that was proved with fixtures: one selected plan produces distinct proposals, a local image preview, an approved due creative, one mock publication, a fake LinkedIn statistics response, stored observations, an attributed enquiry, and a reviewable recommendation. Missing metrics stay null, a returned zero stays zero, a permission failure does not wipe a stored value, a repeated read does not add the totals, another product is not quoted, and a prepared scope makes no live metrics call.

### Native lead-form and supported enquiry ingestion

Acceptance: a fixture LinkedIn or Meta lead form payload, and one supported enquiry payload, each create one consented lead with its source and campaign identifiers. An incomplete or unconsented payload is held. Repeating the provider id does not create a second lead. The lead then uses the existing acknowledgement or outbound path, not a new one.

### Complete paid campaign assembly and attribution

This is the remainder of Milestone 2. Acceptance: the fixture assembles a paused campaign, ad set, creative, and ad aimed at the existing capture form. A submission stores the campaign and ad ids. Zero or missing spend still cannot activate. No spend decimal is written.

### Google Meet creation

This is Milestone 3. Acceptance: the existing calendar create asks for conference data, stores a returned Meet URL, and stores a pending state when Google has not returned one. It does not invent a URL. The prepared demonstration still blocks `calendar.book`. The test uses a fake HTTP client.

### Voice calls, outcomes, and sales handoff

Acceptance: an approved fixture dial uses the mock voice provider, stores the outcome, and creates a follow-up task or a sales handoff only from that stored outcome. A failed dial does not invent a transcript. No live Twilio, Exotel, Vapi, or Dograh call is placed.

### Product-linked commercial activation, onboarding, and retention

This extends Milestone 5. Acceptance: close-won copies the quoted product onto the customer and the onboarding task. A later health or renewal signal references that product. Quote acceptance alone still does not create the customer. No customer email is sent.

### SEO research, publishing integration, and measurement

Acceptance: a fixture keyword and page recommendation are stored against the selected product. Publishing them creates a draft, not a live page. A measurement read stores only figures the fixture provider returned. Search Console is not called.

## Explicitly deferred

- Replacing Gemini, or judging reply quality as a model-vendor problem.
- A new marketing, voice, or post-sale orchestrator.
- Public hosting as a gate for Milestones 1 through 5.
- Starting MinIO, running mailbox sync, running discovery, publishing, booking, dialing, or spending as part of implementation.
- SEO: keyword research, articles, landing pages, metadata, and Search Console.
- YouTube, X, and WhatsApp posting or ads. Google Ads stays `PreparedAdsProvider`.
- Native LinkedIn, Meta, and Google lead forms, and ingestion of comments or direct messages.
- Automatic creative changes, posting-frequency changes, and ad-spend changes. A fixture can store LinkedIn share statistics and a reviewable recommendation. A live metrics request is still unauthorized. Facebook and Instagram insights are not read by the LinkedIn adapter.
- Dograh completion webhooks, the browser widget as a CRM dialer, Exotel/Twilio/Vapi live calls, and public voice callbacks.
- Recall joining a meeting by itself. Milestone 3 only stores a URL.
- Gmail Pub/Sub, live WhatsApp, and live support or finance vendor HTTP.
- Turning quote acceptance into close-won, auto-creating expansion opportunities, or emailing customers from the reconcile beat.
- Training or promoting an ML model. `ML_ALLOW_CHAMPION` stays false.
- Lifting the score gate for unconsented discovery leads, or treating the six local discovery rows that already have `consent_email` as provider consent. Their flag origin is unverified.
- Resuming out-of-office and nurture enrollments, and researching an alternate contact after a wrong-person reply. Those labels can be a later journey once outbound copy is honest.
- Authorizing the prepared demonstration. That is an operator action, not an implementation task.

## Completion of this plan

Milestones 1 and 4, discovery follow-through, and organic creative read-back now pass in fixtures. The post, the lead, and the acknowledgement share the selected product. A content proposal can become one mock publication and a stored LinkedIn statistics reading without a live call. The sequence draft freezes that product and labels the facts behind the email. A discovered person keeps the selected plan and reaches that draft only when assessment and channel permission allow it. No Apify, social, or model provider was contacted to prove this. The next milestone is native lead-form and supported enquiry ingestion. Paid campaign children, Meet, voice, commercial activation, and SEO stay listed above with their own acceptance journeys. None of them inherits a live-provider claim from an older row in the database. The sales engine is not finished.
