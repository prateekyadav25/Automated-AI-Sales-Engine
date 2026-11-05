# Social Growth Autopilot

Facebook and Instagram growth inside the Revenue OS. It reads the client's website into source-backed brand facts, keeps a rolling 30-day calendar for each connected Page and Instagram professional account, renders captions, images, carousels, and 9:16 Reels from a brand template, publishes through Meta's official endpoints, reads insights back with their retrieval time, and attributes traffic, enquiries, qualified leads, and sales separately.

Status on 2026-10-28: complete in fixtures at Alembic `046`. Nothing in this work called Meta, GA4, or an image model with a real account. No post was published, no metric was read from a real account, and nothing was spent. Live publishing and live insight reads are off by default and stay off until an administrator enables them and the workspace is authorized.

On 2026-10-29 the local application was upgraded to Alembic `046` and its images were rebuilt, after a fresh backup. The demonstration scope, holds, and counts were unchanged. See "Deployment" below.

## Gap analysis

What already existed and is reused:

- Social publishers for LinkedIn, Facebook, and Instagram on the operating-plan path. They publish one post per call and keep mock and live separate. They do not plan, render, or read Facebook or Instagram insights.
- `organic_metric_observations` (Alembic `039`) with LinkedIn share statistics only. Facebook and Instagram insights were unsupported.
- The content calendar from `039`: proposals for one operating plan and one image format, with a local preview.
- `SocialImage` and the public media route `/api/v1/public/media/{token}`. Instagram fetches media from that address.
- `execute_external_effect`: the effect is stored before the call, an unknown result is reconciled before any retry, and a confirmed failure is final.
- `external_execution_block` for DEMO workspaces and prepared, authorized, and expired demonstration scopes.
- `AuthorizationGrant` (`bounded_autopilot`), `AIApproval`, and the dispatcher `HANDLERS` registry.
- `run_per_tenant` for workers, `ProviderAccount` token encryption, `assert_public_url` for SSRF checks, `write_audit`, and `emit_event`.
- Public forms, capture tokens, and first-touch attribution on leads.
- The Gemini provider and the prompt registry.

What was missing and is now built:

- Brand facts with the page, the evidence, the time read, the extraction method, and a review state. Only approved facts reach copy.
- Several independently managed Pages and Instagram accounts per workspace, each with its own encrypted token, posting window, daily cap, time zone, and verified permissions.
- A versioned strategy whose pillars cite approved facts, and a rolling calendar that explains each slot.
- Rendering: Pillow brand templates for images and carousels, FFmpeg for 9:16 Reels, and quality gates for each format.
- Instagram container publishing for images, carousels, and Reels. Facebook photos, multi-photo posts, text posts, and Reels. Reconciliation of unknown results. Rate limits.
- Facebook and Instagram insight read-back with freshness, and 1, 7, 30, 90-day and custom reports.
- First-party tracking links, a GA4 Data API boundary, and separate traffic, enquiry, qualified-lead, and sales measures.
- The Social Growth Command Center and five working pages.

Gaps found in existing code, recorded and not changed here:

- Ten tables from Alembic `039`–`045` have no row-level security: `content_proposals`, `content_recommendations`, `deal_purchases`, `lead_form_bindings`, `lead_form_receipts`, `onboarding_completions`, `organic_metric_observations`, `paid_ads`, `purchase_health_signals`, `quote_acceptances`.
- The `collect_organic_metrics` and `retrieve_native_lead_forms` workers run without a tenant context.
- The older Graph clients (ads, lead forms, page posting) are pinned to `v21.0`. Meta lists its expiry as 2027-01-21.
- The capture page did not forward the `publication` and `ad` tokens. That is fixed in this work, together with the new `growth` token.
- The committed OpenAPI artifacts were stale before this work. They were regenerated.
- `ruff check app tests` fails at HEAD on four files this work did not touch.

## Architecture

Request path: `api/v1/social_growth.py` → `services/growth/*` → models. Provider adapters are `providers/meta_growth.py` (Graph), `providers/ga4.py` (GA4 Data API `v1beta`), and `providers/image_generation.py` (optional Gemini imagery). The model never reads the database. `write_caption` sends approved facts and the brief, receives JSON, and falls back to a deterministic caption when the provider is mock or not configured. Every model call is logged in `ModelUsage`.

There is no new orchestrator. Beat runs five tasks through `run_per_tenant`. Publishing goes through `execute_external_effect` with action `social.growth_publish`. A per-post approval is an `AIApproval` handled by the existing dispatcher. Every mutation writes an audit row with the actor, human or AI.

## What must be true before anything posts

`publish_item` checks these in order and stops at the first failure. A stop says why and that nothing was published.

1. `ENABLE_SOCIAL_GROWTH` is on for the workspace. It is off by default.
2. The slot is `scheduled` or `publishing`.
3. The creative is approved and passed every quality check.
4. The creative's content hash is unchanged since approval.
5. The slot's strategy version is approved and not paused.
6. The account token is present, not expired, and not marked for reconnection.
7. The account is not a fixture account. Fixture accounts never reach Meta.
8. The emergency stop and the social channel pause are off.
9. The account's daily cap and the Instagram 24-hour limit are not reached.
10. An execution grant covers the platform, or a person approved this exact creative in the decision inbox. A grant has a platform, a daily cap of 1–25, and an expiry of 1–90 days.
11. `external_execution_block` allows `social.publish`. A DEMO workspace publishes nothing unless an operator authorizes a demonstration scope that covers it. The current scope is `prepared`, which blocks.
12. `SOCIAL_GROWTH_PUBLISH_MODE` is `live`. It is `disabled` by default.
13. For Instagram, every asset is at a public `https` address.

Approving a strategy does not publish. Approving a new strategy version withdraws unpublished work planned under the old one: the slot is re-planned, its creative is marked `superseded`, any pending publish approval is cancelled, and the change is audited. A slot that is publishing, published, failed, skipped, or has a publication record is left alone.

## Brand intelligence

`POST /brand/analyze` reads the client's own website. Each address, including every redirect, passes the SSRF check. `robots.txt` is read first and disallowed paths are skipped. At most `SOCIAL_GROWTH_MAX_PAGES` pages are read, with size limits and the user agent `SalesEngineBrandReader/1.0`. `SOCIAL_GROWTH_BRAND_FETCH_MODE=disabled` reads nothing.

Extraction is deterministic: JSON-LD organization, product, service, address, `sameAs`, and contact data, Open Graph and meta tags, `mailto:` and `tel:` links, social profile links, logo candidates, offer-page headings, numeric and superlative claims, and declared colours. Each fact keeps its page, evidence excerpt, time read, and method. A repeated read updates the same fact and keeps its review state.

Claims start in `needs_review`. Other facts start as `extracted` and are not used until approved. An operator can record a fact. A claim recorded by hand needs a source address or written evidence. Approving or rejecting facts needs `social_growth.approve`. Templates use approved colour facts only. Without one, a neutral palette is used and the creative goes to review.

History import reads the account's recent posts for themes and caption voice. Competitor benchmarks use Instagram Business Discovery and store only the values Meta returned. Hidden counts stay empty.

## Strategy and calendar

A strategy has an objective, an optimization metric, one to eight pillars that each cite approved facts, audiences, a weekly cadence by account and format, a call to action, and a destination (an active enquiry form or an `https` page). The horizon is 7–30 days. Editing a draft keeps its version. Editing an approved strategy creates a new draft. Approval re-validates the facts and accounts and supersedes the previous version.

The planner fills each account's posting windows in that account's time zone, with slot times rounded to 15 minutes and at least 90 minutes of lead time. Each slot's brief stores the pillar, the approved facts and their sources, the format, the audience, the call to action, the destination, the repetition check against the last 60 days of posts and drafts (similarity limit 0.55), the business event if one applies, the strategy version, and a plain rationale. Pillar weights change only when every pillar has at least five measured live posts in 90 days. Until then the verdict is `insufficient_evidence` and pillars rotate evenly.

## Creative production

| Format | Output | Platforms |
|---|---|---|
| Image | 1080×1350 JPEG card | Instagram, Facebook |
| Carousel | 2–10 JPEG slides, one per fact | Instagram, Facebook (multi-photo post) |
| Reel | 1080×1920 H.264/AAC MP4, 30 fps, with a 9:16 cover | Instagram, Facebook |
| Text | Caption and link | Facebook |

Captions use approved facts only. Each number, `#1`, and superlative is checked against the facts. An unsupported claim, a sensitive term from the strategy, a repetition risk, a missing brand colour, or a failed check sends the creative to review. Approving an unsupported claim needs a note of at least 12 characters naming the evidence.

Image checks: JPEG, RGB, exact size, Instagram feed aspect 0.8–1.91 (9:16 for a Reel cover), 8 MB or less, not a placeholder (luminance spread and colour count), commercial provenance, no clipped text, and minimum text contrast 4.5:1.

Reel checks: MP4, H.264, `yuv420p`, 1080×1920, 23–60 fps, 3 seconds to `SOCIAL_GROWTH_REEL_MAX_SECONDS`, video bitrate within limit, AAC, sample rate 48 kHz or less, mono or stereo, `moov` before `mdat`, and 300 MB or less.

Caption checks: present, within 2,200 characters for Instagram (63,206 for Facebook), 30 hashtags or fewer, and no template placeholders. Placeholder words only count in the prose, not inside a link.

Fixture or mock assets, placeholder images, GIFs, and mock clips do not pass. Optional model imagery uses `GEMINI_IMAGE_MODEL` as a background under the brand template. It is off by default.

## Publishing

Instagram (Facebook Login for Business, Graph `META_GRAPH_API_VERSION`):

1. `POST /{ig-id}/media` creates a container. Carousels create child containers first. Reels use `media_type=REELS`, `video_url`, and `cover_url`.
2. `GET /{container}?fields=status_code` until `FINISHED`. `ERROR` and `EXPIRED` are failures.
3. `GET /{ig-id}/content_publishing_limit` is read and `quota_usage` is compared with the returned `quota_total`.
4. `POST /{ig-id}/media_publish`, then the permalink is read.

Facebook: photos are uploaded as multipart JPEG, multi-photo posts use unpublished photos and `attached_media`, text posts use `/feed` with the link, and Reels use `video_reels` start, the byte upload to `rupload.facebook.com/video-upload/{version}/{video-id}`, finish, and `video_status`.

Each container id, child id, and upload id is stored as soon as Meta returns it. The external post id, permalink, API version, attempts, and failure class are stored on the publication. The effect key includes the content hash and an epoch. An unknown result is reconciled before any retry: the container status is read, then recent media are matched by caption hash. A person can mark an unresolved post `published` with its id or `not_published`, which advances the epoch. Graph errors are classified as AUTH, PERMISSION, RATE_LIMIT, PUBLISH_LIMIT, TRANSIENT, INVALID, or NETWORK. AUTH marks the account for reconnection. Rate limits honour Meta's usage headers.

Meta's documentation disagrees on the Instagram limit. The content-publishing guide says 100 posts in 24 hours. The `content_publishing_limit` and `media_publish` references say 50. The local pre-check defaults to 50 (`SOCIAL_GROWTH_INSTAGRAM_DAILY_LIMIT`), and the live `quota_total` is read again before every publish.

## Insights and reporting

| Scope | Metrics |
|---|---|
| Instagram account | `views`, `reach`, `accounts_engaged`, `total_interactions`, `profile_links_taps`, and `follower_count` |
| Instagram post | `views`, `reach`, `likes`, `comments`, `saved`, `shares`, `total_interactions`, `follows`, `profile_visits`. Reels: `ig_reels_avg_watch_time` instead of follows and profile visits |
| Facebook Page | `page_media_view`, `page_total_media_view_unique`, `page_post_engagements`, `page_daily_follows_unique`, `page_views_total`, `page_total_actions` |
| Facebook post | `post_media_view`, `post_total_media_view_unique`, `post_clicks`, and `post_video_views` for video |

Facebook impression metrics were replaced by `page_media_view` and `post_media_view`, and reach by `page_total_media_view_unique` and `post_total_media_view_unique`. A metric Meta refuses is retried alone so one refusal does not drop the others.

Each reading stores the account or post, the period and period end, the value, the retrieval time, the endpoint, the API version, the provenance, and a status of `recorded`, `unavailable`, `unsupported`, or `failed`. A missing value stays null and is shown as "Unavailable", never zero. A failed reread keeps the stored value.

Reports cover 1, 7, 30, and 90 days or a custom range, as UTC days with an exclusive end. Daily additive metrics are summed. Unique metrics are averaged per day and labeled as such, because unique people cannot be added across days. Follower counts use the latest reading. Each metric shows its coverage (for example "Partial: 3 of 7 days"). Fixture readings are labeled and never added to live readings. The report notes that Meta can delay insights by up to 48 hours.

## Website and lead attribution

Each slot with a destination gets a tracking link, `/api/v1/public/r/{token}`. It redirects to the destination with `utm_source` (the platform), `utm_medium=social_organic`, `utm_campaign=social-growth-v{version}`, and `utm_content` (the slot). A form destination also carries the `growth` token. Clicks are stored with the time, the referrer host, and a bot flag. No IP address is stored. Link-preview crawlers and automated agents are counted separately and excluded.

The capture page forwards the `growth`, `publication`, and `ad` tokens. A submission with a `growth` token stores the link on the capture. The lead takes it as first touch only when it has no earlier touch.

Measured separately:

| Measure | Definition |
|---|---|
| Tracked link clicks | Human redirects through this engine's links |
| Website sessions | GA4 `sessions`, `totalUsers` (daily sum), and `keyEvents` by `sessionSource`, `sessionMedium`, `sessionCampaignName`. Unavailable until GA4 is connected |
| Enquiries | Form submissions that carried a growth token |
| Qualified leads | Attributed leads with a stored sales-qualified assessment |
| Sales | Won purchases on attributed leads, by currency. Fixture amounts are separate. Currencies are not combined |

## Recommendations

Recommendations compare formats, pillars, posting times, and account health using measured live posts only. Each one needs at least five posts per group. Without them the verdict is `insufficient_evidence`. A recommendation is a proposal. Applying one does not change the strategy, the calendar, or a creative by itself.

## Data model, Alembic `046`

New tables, all with `tenant_id`, forced row-level security, and grants to `agrayian_app`:

`growth_accounts`, `brand_profiles`, `brand_sources`, `brand_facts`, `competitor_benchmarks`, `growth_business_events`, `growth_strategies`, `growth_calendar_items`, `growth_creatives`, `growth_assets`, `growth_publications`, `growth_media`, `growth_metric_observations`, `growth_tracking_links`, `growth_link_clicks`, `growth_traffic_observations`, `growth_recommendations`.

`growth_tracking_links` also allows the public redirect to read one row by `token_hash`. `leads` and `inbound_captures` gain an indexed `growth_link_id`. The migration adds `social_growth.read`, `social_growth.write`, and `social_growth.approve`, grants them by role, and adds `ENABLE_SOCIAL_GROWTH=false` for every tenant. Downgrade is a no-op. Recovery is restoring the backup taken before the upgrade.

| Role | read | write | approve |
|---|---|---|---|
| Super Admin, Tenant Admin, CEO, CRO, CMO, Sales Director | yes | yes | yes |
| Sales Manager | yes | yes | no |
| Sales Rep, Read Only | yes | no | no |

## API

All routes are under `/api/v1/social-growth`. Read routes use `social_growth.read`.

| Route | Permission |
|---|---|
| `GET /overview`, `GET /brand`, `GET /accounts`, `GET /strategy`, `GET /calendar`, `GET /creatives/review`, `GET /creatives/{id}`, `GET /publications`, `GET /performance`, `GET /attribution`, `GET /grants`, `GET /recommendations` | read |
| `POST /brand/analyze`, `PUT /brand/settings`, `POST /brand/facts`, `POST /brand/competitors` | write. A new fact is approved only when the caller also has approve |
| `POST /accounts`, `POST /accounts/{id}/disconnect` | write and `integrations.write` |
| `POST /accounts/fixture`, `POST /accounts/{id}/verify`, `PATCH /accounts/{id}`, `POST /accounts/{id}/history`, `POST /accounts/{id}/insights` | write |
| `PUT /strategy`, `POST /events`, `DELETE /events/{id}`, `POST /calendar/plan`, `POST /calendar/{id}/skip`, `POST /calendar/{id}/creative`, `PATCH /creatives/{id}`, `POST /ga4/collect`, `POST /recommendations/generate` | write |
| `POST /brand/facts/review`, `POST /strategy/{id}/approve`, `POST /strategy/pause`, `POST /calendar/{id}/schedule`, `POST /calendar/{id}/publish`, `POST /creatives/{id}/review`, `POST /publications/{id}/resolve`, `POST /grants`, `POST /grants/{id}/revoke`, `POST /recommendations/{id}/decide` | approve |

Public: `GET /api/v1/public/r/{token}` redirects (302, `no-store`, 120 requests a minute per address). An unknown token returns 404.

## Workers

| Beat entry | Every | Does |
|---|---|---|
| `growth-plan-calendars` | 1 hour | Plans the rolling calendar for an approved strategy |
| `growth-prepare-creatives` | 10 minutes | Produces creative for up to 4 slots due within 72 hours when the strategy allows automatic creation |
| `growth-publish-due` | 1 minute | Publishes due scheduled slots. Does nothing unless publishing is live |
| `growth-collect-insights` | 1 hour | Reads insights. Does nothing unless insight reads are live |
| `growth-collect-ga4` | 1 day | Reads GA4. Does nothing unless GA4 is live and connected |

Each task does nothing for a workspace with `ENABLE_SOCIAL_GROWTH` off, and records an `AutonomousRun` when it acts.

## Settings

| Setting | Default |
|---|---|
| `META_APP_ID`, `META_APP_SECRET` | empty. Needed to verify tokens and send `appsecret_proof` |
| `META_GRAPH_API_VERSION` | `v26.0` |
| `SOCIAL_GROWTH_PUBLISH_MODE` | `disabled` |
| `SOCIAL_GROWTH_INSIGHTS_MODE` | `disabled` |
| `SOCIAL_GROWTH_BRAND_FETCH_MODE` | `live` (public website reads only) |
| `SOCIAL_GROWTH_MAX_PAGES` | 12 |
| `SOCIAL_GROWTH_REEL_MAX_SECONDS` | 90 |
| `SOCIAL_GROWTH_CAROUSEL_MAX` | 10 |
| `SOCIAL_GROWTH_INSTAGRAM_DAILY_LIMIT` | 50 |
| `GA4_MODE` | `disabled` |
| `GEMINI_IMAGE_MODEL` | empty (no model imagery) |
| `CREATIVE_FONT_PATH`, `CREATIVE_FONT_BOLD_PATH`, `FFMPEG_PATH`, `FFPROBE_PATH` | empty (system fonts and `PATH`) |

## Pages

`/growth` (command center), `/growth/brand`, `/growth/accounts`, `/growth/calendar`, `/growth/studio`, and `/growth/performance`, in a "Social Growth" workspace in the main navigation. Each page has loading, empty, error, and permission-denied states. Read-only users see the pages without write or approve controls.

## Evidence

All of this is fixture evidence. None of it is live Meta, GA4, or image-model evidence.

- API: 37 growth tests and the Postgres migration test pass. The full suite has 367 passed, 16 skipped, and the same 15 failures as a clean checkout of HEAD.
- Migration: a fresh database migrated `001`→`046` and seeded. A restored copy of the live `045` backup upgraded to `046` with the demonstration scope, holds, approvals, leads, meetings, emails, customers, and tenant modes unchanged. The copy was dropped.
- Web: `tsc`, ESLint, and vitest pass. `next build` compiles, lints, and type-checks. On Windows its final standalone copy fails on a symlink permission. The Linux image build does not use that step.
- Browser: `apps/web/e2e/growth.spec.ts` passed five consecutive runs against a separate stack (a disposable Postgres database at `046`, API on 8100, web on 3100, Redis database 9). It covers the command center with live modes off, approved facts, fixture accounts, an approved strategy, a planned calendar, a rendered image and Reel, approval in the studio, scheduling that waits in the inbox, a publish attempt that is refused, a visitor following the tracking link to the capture form and submitting it, a link-preview crawler counted as automated, read-only limits, and another workspace seeing none of it.
- Container: in the Linux API image (FFmpeg 7.1.5, DejaVu fonts) a rendered card passed every image check and a two-scene Reel passed all 12 Reel checks.
- The browser runs found two defects that are now fixed: a random tracking token could trip the placeholder check, and approving a new strategy left in-flight slots stranded under the old version.
- Static checks: `bandit` on the new backend code reports no medium or high findings. The five low findings are the FFmpeg and ffprobe subprocess calls (fixed argument lists, no shell), the subprocess import, an empty string that clears a revoked token, and an ignored HTML parser error on a malformed page. The Aikido scan was not run because it needs a sign-in.

## Deployment

The API image installs `ffmpeg` and `fonts-dejavu-core`. CI installs the same packages for the API and both Playwright jobs, and the Playwright jobs set `WEB_APP_ORIGIN` and `PUBLIC_API_BASE_URL` to `127.0.0.1` so the tracking-link redirect lands on an allowed origin.

The Compose API runs `alembic upgrade head` and the demo seed at start, so rebuilding the API image applies `046`. The local stack was upgraded this way on 2026-10-29:

1. A backup was taken at `045`: `.local-backups/agrayian-before-046-2026-10-29.dump`.
2. Api, worker, and beat were stopped.
3. Api, worker, beat, and web were rebuilt and started with `--no-deps`, so MinIO stayed off. The API applied `046`.
4. The demonstration scope, holds, approvals, leads, meetings, emails, customers, and tenant modes were unchanged.

The first start showed a seed defect: the new caption prompt for the second tenant was added but not flushed before the seed switched tenant context, so row-level security refused it and the whole seed rolled back. The seed now flushes prompts while the tenant's context is set. The fix was checked on a restored copy, then the API was rebuilt and the seed completed.

To roll back, stop api, worker, and beat, `pg_restore --clean --if-exists` that dump into `agrayian`, and start images built from the previous commit.

## Meta onboarding and live verification

Live verification needs all of the following. None of it is in place.

1. A Meta app using Facebook Login for Business. Put its id and secret in `META_APP_ID` and `META_APP_SECRET`.
2. Permissions: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `read_insights`, `instagram_basic`, `instagram_content_publish`, and `instagram_manage_insights`. Advanced Access through App Review is needed for Pages the app's business does not own. When the person's Page role comes through Business Manager, Meta also asks for `ads_read` or `ads_management`. A Page that requires Page Publishing Authorization cannot publish to its Instagram account until that is complete.
3. For each client: a long-lived Page access token, the Page id, and the Instagram professional account id linked to that Page. Enter them on the accounts page. "Verify" reads `debug_token` and records the granted and missing permissions, token expiry, and data-access expiry.
4. A public `https` `PUBLIC_API_BASE_URL` that Meta can fetch, serving `/api/v1/public/media/{token}`, and shared object storage (MinIO or S3) so every container serves the same files.
5. An authorized workspace. The demonstration scope is `prepared`, so it blocks publishing until an operator authorizes it for `social.publish`.
6. `ENABLE_SOCIAL_GROWTH` on for that workspace, `SOCIAL_GROWTH_PUBLISH_MODE=live` and `SOCIAL_GROWTH_INSIGHTS_MODE=live`, an approved strategy, an approved creative, and a grant or an inbox approval.
7. For GA4: a Google connection with `analytics.readonly`, the GA4 property id on the brand page, and `GA4_MODE=live`.

Suggested order, read-only first: verify the token, import history, read insights, read GA4, then one separately authorized test post to an account the client owns.

## Limits

- No live publish, live insight read, or live GA4 read was made. Live behaviour is unproven until the checks above run.
- Stories, comments, direct messages, mentions, and paid boosting are not supported. There is no engagement automation, follow/unfollow, or amplification, by design.
- Facebook carousels are multi-photo posts.
- Captions use Gemini when it is configured and a deterministic template otherwise. Model imagery is off by default.
- Competitor benchmarks need `instagram_manage_insights` and return only what Business Discovery exposes.
- GA4 attribution is session-level by source, medium, and campaign. It is not user-level.
- The existing gaps listed under "Gap analysis" remain.
