# Milestone 050 — Full Meta Ads Autopilot

Date: 2026-11-07. This is a plan. It is not an implementation, and it does not authorize a campaign, an activation, or spend.

Do not start this milestone until milestone 049 has all three of these, from a real provider, stored in staging:

1. A verified Page and linked Instagram professional account, with granted and missing permissions recorded from Meta.
2. At least one separately authorized post with a provider publication id and a read-back permalink.
3. A tracking link, redirect, and enquiry for that post in the same workspace, with source attribution stored and fixture rows kept out of the report.

Until then, `META_ADS_MODE` stays `disabled` on staging and on the demonstration.

## What already exists

Paused website-form assembly is fixture-tested in `apps/api/app/services/ads_assembly.py`.

- Objective `traffic`, placement `facebook_feed`, destination the existing capture form.
- Assembly version string `meta-paused-website-v21.0`. That string is a recipe id. Organic Graph calls use `META_GRAPH_API_VERSION` (default `v26.0`). 050 must not treat the recipe id as the live Marketing API version.
- The module does not call `activate_campaign` or `execute_ads_spend`.
- A provider client is used only when the caller supplies one. The assembly does not open a live Meta connection.
- A saved budget is not permission to spend.
- LinkedIn assembly and native lead-form campaign creation stay unsupported in this module.
- `execute_ads_spend` in `apps/api/app/services/ads.py` is a separate path. It already stops on `external_execution_block` and an approval. 050 must not call it from organic publishing, from the acceptance checklist, or from a scheduler.

## Architecture

Keep the existing boundary: the model proposes, a person approves, a service calls the provider, and the repository writes only that tenant's rows.

- A Page token and the organic scopes do not prove an ad account. Store a separate ad-account connection: ad account id, currency, timezone, business id, and its own encrypted token.
- Required permissions are `ads_management` and `ads_read`, checked with a read-only debug call after a dedicated authorization. `business_management` is required only if the token cannot see the ad account without it. Record granted and missing scopes. Do not infer them.
- Billing and account status are read-only facts. A disabled or unsettled ad account cannot be assembled.
- Create objects paused: campaign, ad set, creative, ad. Store each returned id before creating the next object. A campaign shell alone is not complete.
- Activation and spend are a second external effect, with its own idempotency key, its own approval, and a daily and monthly cap in the ad account currency. The cap is deterministic. The model does not invent the amount.
- Organic acceptance gates are not ads gates. Add separate steps, for example `ads_account`, `ads_paused_create`, and `ads_activate`. Authorizing one does not authorize the others.
- Insights are readings with endpoint, API version, period, retrieval time, and provenance `provider`. Missing values stay null and display as unavailable. Fixture ads readings never enter live totals.
- A closed loop may write a recommendation. It may not change a bid, a budget, a status, or a creative unless a person approves that exact change.
- Tenant isolation, audit, and unknown-effect reconciliation match organic publishing. An unknown create or activate stays unknown and is read back before another attempt.

## Implementation order

1. Migration for the ad-account connection and the three acceptance steps, with `tenant_id` and forced row-level security. Recovery is a pre-upgrade dump. Do not apply it to database `agrayian` while the demonstration is on `046`.
2. Repository and service for storing the ad account. Encrypt the token with `TOKEN_ENCRYPTION_KEY`. Never return the token. Redact it from logs, errors, and audit payloads.
3. Read-only identity and permission check, behind the `ads_account` gate and `META_ADS_MODE=disabled` until that one call is explicitly enabled and then disabled again.
4. Paused assembly through the existing website-form path, using the live Marketing API version from settings, behind `ads_paused_create`. Create paused only.
5. A separate activate path with spend caps, behind `ads_activate`. Default remains off. One test activation requires its own yes, a cap, and a read-back of the effective status. Then return ads mode to `disabled`.
6. Insight read-back into the organic planner as recommendations only.
7. Tests with scripted clients that cannot become `verified_live`. A live check uses provider evidence the process recorded, same rule as organic acceptance.
8. Docs and an operational checklist. No autonomous spend for a client.

## Stop conditions

- Do not start until the 049 prerequisites above are stored.
- Do not spend, unpause, or raise a budget without an exact approval for that action.
- Do not send email or messages from an ad flow.
- Do not point staging DNS, credentials, or volumes at the demonstration.
- Do not mark a fixture campaign live-verified.
- Do not enable a scheduler that creates or activates ads.
