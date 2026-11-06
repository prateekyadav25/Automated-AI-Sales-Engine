# Social Growth release readiness — milestone 048

Date: 2026-11-06. Branch: `social-growth-047-hardening`. This report is the staging result. It is not a claim that a live Facebook or Instagram call succeeded.

The running demonstration was not restarted and was not migrated. Its Alembic version is still `046`. Nothing was published, advertised, spent, emailed, or messaged.

## 1. Deployment status

| Component | Staging | Demonstration |
|---|---|---|
| Postgres | `agrayian-staging-postgres-1`, host port 5436, Alembic `048` | `salesengine-postgres-1`, host port 5435, Alembic `046` |
| Redis | `agrayian-staging-redis-1`, host port 6381 | `salesengine-redis-1`, host port 6380 |
| Object storage | Silo on host ports 9002/9003, bucket `agrayian-staging`. A health object was written and read back. | Not part of this change. The demonstration MinIO container is not running. |
| API | `http://localhost:8012`, `GET /health` returned 200, environment `staging` | `http://localhost:8002`, left running |
| Web | `http://localhost:3010` returned 200 | `http://localhost:3000`, left running |
| Worker | Healthy. Inbox backlog tasks returned 0. | Left running |
| Beat | Healthy. One replica. | Left running |
| Public HTTPS | Not configured. `PUBLIC_API_BASE_URL` is `http://localhost:8012`. | Unchanged |

`docker-compose.staging.yml` does not read `.env` and does not use the demonstration volumes. Official MinIO images no longer pull anonymously, so object storage uses `pgsty/silo:RELEASE.2026-10-26T00-00-00Z`. The passwords in that file are for this machine only.

Celery 5.7 and a fresh Celery 5.6 install import `packaging`, which those releases do not declare. The API dependency is pinned to `celery>=5.4.0,<5.7` and `packaging>=24`. The demonstration image was not rebuilt.

## 2. Migration and database verification

- Code head is Alembic `048`, which follows `047`, which follows `046`.
- `tests/test_migration_048.py` upgraded a new database to `048`, forced row-level security on the ten `047` tables plus `growth_accounts` and `growth_acceptance_gates`, and left the application database at `046`.
- A restore of `.local-backups/agrayian-before-sample-retirement-2026-10-29.dump` into disposable database `m048_restore` was at `046` with 2 tenants, 9 accounts, 43 leads, 0 growth accounts, and 862 audit rows. After `047` and `048`, those counts were unchanged and `growth_acceptance_gates` was empty. The copy was dropped. The demonstration version was still `046`.
- Staging itself migrated an empty database to `048`. `growth_publications` is 0.
- A staging `pg_dump` restored into `staging_restore` on the staging Postgres server was also `048`. That copy was dropped. The demonstration database was not the target.

`047` and `048` downgrades are no-ops. Recovery is restoring a dump taken before the upgrade.

## 3. Tenant-security results

| Check | Result |
|---|---|
| Workspace A cannot read or write workspace B | On the disposable database, the app role with tenant A and `app.lead_intake=1` saw only tenant A's growth account. An insert for tenant B failed row-level security. |
| Growth tables | `growth_accounts` and `growth_acceptance_gates` are forced. Growth policies from `046` remain. |
| Ten legacy tables | The ten `047` tables still have forced row-level security after the upgrade to `048`. |
| Lead-form intake exception | `app.lead_intake` is in the lead-receipt policy and is absent from `content_proposals`, `growth_accounts`, and `growth_acceptance_gates`. |
| Tenant-scoped workers | `collect_due_organic_metrics` for an unknown tenant returns 0. Growth tasks still use `run_per_tenant`. |
| Public tracking and media | Unknown tracking tokens are refused (`test_public_redirect_route_refuses_unknown_tokens`). Public media resolves one token hash and returns 404 for any other token. |
| Expired or revoked Meta tokens | Existing release-gate test: no Graph call and no publication. |
| Second scheduler tick | Before authorization, a live-mode scheduler tick made no Graph call. After authorization, one publish was recorded and the second tick published nothing. |
| Unknown external effects | The existing test still reconciles an unknown effect and does not post `media_publish` again. |
| Backup and recovery | Staging dump, restore, and drop succeeded on the staging server only. |

## 4. Remaining CI failures

Re-run with `AGRAYIAN_ENV_FILE=/nonexistent`. Eight tests failed. They are the same pre-existing assertion mismatches. They are not Social Growth release blockers and they do not gate publishing.

| Test | What it expected | What it got | Severity |
|---|---|---|---|
| `test_operating_plan_publishes_only_an_authorized_version` | the word "unknown" | a mock publication outcome | Low. Copy assertion. |
| `test_no_consent_does_not_queue_send` | the word "consent" | an assessment sentence that says outbound is not permitted | Low. Copy assertion. |
| `test_valid_search_results_persist_provenance` | a stored discovery row | an empty result | Medium for discovery, not for growth. No provider was configured. |
| `test_open_circuit_returns_last_vendor_error` | a HarvestAPI message | the DEMO paid-discovery block | Low. The block is the safer outcome. |
| `test_money_ledger_worker_and_scopes` | "failed to execute" | the demonstration block, nothing sent | Low. Copy assertion. |
| `test_scopes_block_before_any_calendar_call` | "failed to execute" | the demonstration block, nothing sent | Low. Copy assertion. |
| `test_replay_does_not_duplicate_onboarding_and_scopes_release_nothing` | "failed to execute" | the demonstration block, nothing sent | Low. Copy assertion. |
| `test_scopes_and_worker_place_no_call` | "failed to execute" | the demonstration block, nothing sent | Low. Copy assertion. |

`ruff check` on the changed Python files passed. Aikido still needs a sign-in, so it was not run. The suite was not run with the developer env file, because that file holds live provider settings.

## 5. Real provider connections still needed

None of these are set on staging:

- `META_APP_ID` and `META_APP_SECRET`
- A long-lived Page token and the linked Instagram professional account id, entered in the product, not committed
- `PUBLIC_API_BASE_URL` on a public `https` origin
- A saved GA4 property id and a Google connection with `analytics.readonly`
- `TOKEN_ENCRYPTION_KEY` separate from `SECRET_KEY` before any real token is stored on a shared host

The hosted repository `OHA2025g/Sales_Engine` does not have this branch. Do not deploy it there until that remote is updated on purpose.

## 6. Published external effects

None. Staging has zero growth publications. No Graph, GA4, ad, email, or message call was made for this milestone.

## 7. Conditions required before enabling publishing

All of these, in order:

1. Staging is the target, not the demonstration database.
2. `PUBLIC_API_BASE_URL` is the public `https` origin Instagram can fetch.
3. The Meta app id and secret are present, and Verify has stored granted scopes, expiry, and data-access expiry for the named Page and Instagram account.
4. The account is `connected`, publishing-eligible, and insight-eligible. A missing permission or an expired token stops at reconnect.
5. A person with `social_growth.approve` authorizes `facebook_post`, `instagram_image`, or `instagram_reel` on `/growth/acceptance`. The note names the account and the action. Authorization alone does not publish.
6. `SOCIAL_GROWTH_PUBLISH_MODE=live` for that one check. Insights and GA4 can stay disabled.
7. The workspace flag is on, the strategy and creative are approved, and a grant or inbox approval exists for that creative.
8. The workspace is not a prepared DEMO scope.
9. One post only. Confirm the provider id and permalink, then set publish mode back to `disabled`.

A fixture account cannot pass these conditions. A scripted result cannot become `verified_live`.

## 8. Recovery

1. Leave the demonstration containers and database `agrayian` alone.
2. For staging, `pg_dump` the staging database before a migrate or a publish check.
3. Restore that dump into a new database on the staging Postgres server. Confirm Alembic `048` and that publish mode on the copy is disabled.
4. `047` and `048` have no downgrade. To undo them, restore the dump taken before the upgrade.
5. To remove the local staging stack: `docker compose -p agrayian-staging -f docker-compose.staging.yml down`. Add `-v` only when the staging volumes should be deleted. Do not run that against the demonstration project.

## 9. Recommended next milestone

Do not start Meta Ads Autopilot yet. The next milestone is one authorized live token check, one historical read, and one approved post on this staging stack, each with its own yes. After that post has a stored provider id, the closed loop can read organic outcomes back into the planner. Paid campaign activation stays behind a separate spend approval.
