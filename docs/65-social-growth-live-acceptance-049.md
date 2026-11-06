# Social Growth live acceptance — milestone 049

Date: 2026-11-07. Branch: `social-growth-047-hardening`, continued from `519aff4`.

**Status: partially complete. BLOCKED BY CONFIGURATION.**

A real Meta account has not been verified. No post has been published. No permalink, insight value, GA4 row, or enquiry from a live post exists. Milestone 049 is complete only when those three things are true: a real account verified from provider results, one separately authorized post confirmed by a provider id and a read-back permalink, and the tracking path for that post checked with a real enquiry. None of those happened.

The running demonstration was not restarted and was not migrated. Its Alembic version must stay `046`. Nothing was published, advertised, spent, emailed, or messaged. The branch was not pushed and was not merged.

## 1. Real Meta connection status

Not connected. Staging has no `META_APP_ID`, no `META_APP_SECRET`, and no Page token. `GET /api/v1/social-growth/acceptance/preflight` reads settings only. It reports `meta_app_configured: false` and the sentence `BLOCKED BY CONFIGURATION`. No Graph request was made.

What is required before the first live request:

1. A Meta app the business owns, with the app id and app secret entered in the staging environment, not in Git.
2. A long-lived Page token for a Page the operator owns, entered through the accounts screen. The token is encrypted at rest and is not returned by the API.
3. The numeric Facebook Page id and the linked Instagram professional account id.
4. A workspace that is not a prepared DEMO scope.
5. A separate yes for token verification before Verify is pressed. Verify is the first external request.

## 2. Permissions verified

None. No token was presented to Meta, so granted and missing permissions are unknown.

The checklist still expects these scopes before a later publish or insight read: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `read_insights`, `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`. A missing scope leaves the account unverified. That check has not been run.

## 3. Public media readiness

**BLOCKED BY CONFIGURATION.** Staging `PUBLIC_API_BASE_URL` is `http://localhost:8012`. Instagram cannot fetch that address. There is no public hostname, no DNS record, and no TLS certificate for this staging stack.

What is already in place on the isolated stack:

- Shared S3-compatible storage: Silo, bucket `agrayian-staging`, used by the API and the worker. The demonstration volumes are not mounted.
- Growth assets are stored as `image/jpeg`, `image/png`, or `video/mp4`. The public media route returns the stored content type and `X-Content-Type-Options: nosniff`.
- The URL given to a provider is `{PUBLIC_API_BASE_URL}/api/v1/public/media/{token}`. The token is 32 bytes from `secrets.token_urlsafe`. It is not a presigned bucket URL. It does not expire on a timer, because Meta can fetch the file after container processing. Revocation is deleting the asset or disconnecting the account. `Cache-Control: public, max-age=86400` is a cache hint, not an access expiry.
- Staging published ports are bound to `127.0.0.1` only: Postgres `5436`, Redis `6381`, object storage `9002`, Silo console `9003`, API `8012`, web `3010`. PostgreSQL, Redis, and the Silo console are not published on the LAN.
- Fixture and mock assets are not presented as production creatives. Scripted tests stay provenance `live` or fixture and are not `verified_live`.

Exact setup still required, and not performed:

1. Choose a hostname that is not the demonstration host and not `revanza.demo.agrayianailabs.com` or `revanza.demoapi.agrayianailabs.com`.
2. Create a DNS A, AAAA, or CNAME to a machine that can reach the staging API on localhost `8012`. Do not point it at the demonstration on port `8002` or database `agrayian`.
3. Issue a valid TLS certificate for that hostname (Let's Encrypt or the platform certificate).
4. Reverse-proxy only `https://<host>/api/v1/public/media/` and `https://<host>/api/v1/public/r/`. Do not proxy Postgres, Redis, the Silo console, or the administrator UI.
5. Set `PUBLIC_API_BASE_URL` on the staging API and worker to `https://<host>`. Do not change the demonstration's `PUBLIC_API_BASE_URL`.
6. Fetch one jpeg or png and one mp4 through that HTTPS URL and confirm the content type. Use an asset created for the test, not a fixture labeled as a client creative.
7. Set `TOKEN_ENCRYPTION_KEY` on staging before storing a real Page token.

Until those exist, Instagram image and Reel publication stay blocked even if an operator later approves them.

## 4. Publications and permalinks

None. After the staging project was recreated with this code, Alembic is still `048`, `growth_publications` is 0, and there are no users. `GET /health` returned 200 with environment `staging`. Publishing, insights, GA4, and ads are `disabled`. Preflight status is `blocked`, `https_media` is false, and the Meta app is not configured. Published ports are `127.0.0.1` only. The demonstration health check returned 200, its Alembic version is `046`, and its containers were not recreated.

Three scripted cases exist so a future one-post test has an independent path. They use a fake Graph client. They are not live posts:

| Case | Scripted result | Live status |
|---|---|---|
| A. One Facebook image | Provider id and permalink stored from the fake response | `facebook_post` is not `verified_live` |
| B. One Instagram image | One `media_publish` call, external id stored | `instagram_image` is not `verified_live` |
| C. One Instagram Reel | Reel format and an https permalink from the fake | `instagram_reel` is not `verified_live` |

Each case left `SOCIAL_GROWTH_PUBLISH_MODE` unchanged. `publish_due` returned 0. The Beat task `growth_publish_due` still runs every 60 seconds and no-ops while the mode is disabled. A one-post test must not turn that mode on and leave it on. After any future live post, set the mode back to `disabled` and confirm preflight still shows publishing disabled.

If a future provider response is unknown, the publication stays `UNKNOWN` and must be reconciled before another attempt.

## 5. Insight and GA4 availability

Unavailable. `SOCIAL_GROWTH_INSIGHTS_MODE` and `GA4_MODE` are `disabled`. No historical import, no Facebook or Instagram insight read, and no GA4 collect ran. There is no GA4 property id and no Google connection. Missing metrics stay unavailable. They are not stored as zero. Fixture readings are not mixed into a live report because there is no live report.

## 6. End-to-end attribution evidence

None from a live post. No tracking link was created for a real publication, no redirect was fetched from outside this machine, and no test enquiry was submitted. The redirect route remains `GET /api/v1/public/r/{token}` and refuses unknown tokens. That path is fixture-tested from earlier milestones. It has not been checked against a post Meta actually delivered.

## 7. Remaining blockers and known defects

Blockers:

- No public HTTPS origin. BLOCKED BY CONFIGURATION.
- No Meta app id or secret. BLOCKED BY CONFIGURATION.
- No Page token and no Instagram professional account id.
- No dedicated `TOKEN_ENCRYPTION_KEY` on staging. A stored token would be encrypted with the application secret.
- No operator authorization for token verification, history import, insights, GA4, or any of the three posts.
- No GA4 credentials.
- The feature branch is one or more commits ahead of `origin/social-growth-047-hardening` and is not on `OHA2025g/Sales_Engine`. Do not push without an explicit yes. The earlier push to `sales-engine` was denied for this GitHub user.

Known defects that do not block a future live Meta test:

Eight API tests still fail with `AGRAYIAN_ENV_FILE=/nonexistent`, reproduced again on 2026-11-07. They fail on wording or because a DEMO guard returns before an older path. They do not release an external action.

| Test | What failed | What did not happen |
|---|---|---|
| `test_operating_plan_publishes_only_an_authorized_version` | Expected the word "unknown"; the mock publisher says the outcome is not a verified live post | No live LinkedIn post |
| `test_no_consent_does_not_queue_send` | Expected the word "consent" in an assessment sentence | No send approval; state stays blocked |
| `test_valid_search_results_persist_provenance` | Empty discovery result | The paid-discovery vendor is not reached for a DEMO workspace |
| `test_open_circuit_returns_last_vendor_error` | Expected "HarvestAPI"; received the DEMO paid-discovery block | `created` is 0. The stand-in vendor was not called |
| `test_money_ledger_worker_and_scopes` | Expected the prepared-scope sentence; received the DEMO "Nothing was sent" sentence | `external_released` is false |
| `test_scopes_block_before_any_calendar_call` | Same wording mismatch | No calendar call |
| `test_replay_does_not_duplicate_onboarding_and_scopes_release_nothing` | Same wording mismatch | Nothing released |
| `test_scopes_and_worker_place_no_call` | Same wording mismatch | No call placed |

A live Meta test still needs a workspace that is not a prepared DEMO scope, plus the acceptance gate and an explicit limited publish mode for that one action.

Aikido scan was not run. The scanner requires a sign-in, and that login was not started.

## 8. Client onboarding prerequisites

Before a client workspace can be considered for one controlled post:

1. Isolated staging, not the demonstration database.
2. The HTTPS origin from section 3, with media content types confirmed.
3. `TOKEN_ENCRYPTION_KEY` set only on staging.
4. Meta app credentials in the staging environment.
5. App Review / Advanced Access for the Page and Instagram permissions in section 2.
6. A Page and Instagram professional account the client owns, connected in that client's tenant.
7. An approved brand strategy and an approved creative whose content hash is unchanged.
8. A publication grant or an exact-item approval.
9. Separate authorization on `/growth/acceptance` for the specific step.
10. Publishing enabled only for that test, then set back to disabled.
11. Consent and do-not-contact respected before any enquiry follow-up. This milestone sends no email and no message.

Do not enable recurring automatic publishing for a client as part of onboarding.

## 9. Operational readiness

Not ready for a live client. Staging can boot the Social Growth code with publishing, insights, GA4, and ads held off. The acceptance screen can record an authorization without calling a provider. It cannot yet prove a provider result.

Recovery that is already designed, and was not re-proven against Meta because Meta was not called:

- Disconnect, expiry, and revocation stop in `token_problem` before a Graph call.
- An unknown publish result stays unknown and is reconciled before retry.
- A second scheduler tick does not post again while publish mode is disabled.
- Growth tables keep forced tenant row-level security from milestones 046–048.
- Connect-account audit stores platform, external id, page id, and status. A regression test checks that the raw token is absent from the audit JSON and from the account API payload.
- Graph error text and log lines redact `access_token`, `input_token`, `appsecret_proof`, `client_secret`, `refresh_token`, and `app_secret` query values.

Rate limits, failed asset fetches, and media processing errors have fixture coverage from earlier milestones. They have no live provider example.

## 10. Next phase

Milestone 050 is planned in `docs/66-meta-ads-autopilot-050.md`. It has not been started. `META_ADS_MODE` stays `disabled`. No campaign was created and nothing was spent.
