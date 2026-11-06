# Social Growth live acceptance

Run these in order on the isolated staging stack from `docs/62-social-growth-staging.md`. The same steps are on `/growth/acceptance`. Each one is `not_started`, `blocked`, `awaiting_authorization`, `verified_live`, `failed`, or `not_supported`. `verified_live` is computed from a provider result recorded by a client this process opened. A fixture, a scripted client, or a row marked live without that provider mark does not count. Authorizing a step records the person and the note. It does not call Meta or Google.

Each step that would call Meta, Google, or publish a post stops at the approval line. Do not continue past that line without a separate yes for that step. Fixture accounts and `SOCIAL_GROWTH_PUBLISH_MODE=disabled` are the default. A DEMO workspace with a prepared scope publishes nothing.

Record the workspace, the account name, the operator, and the time for every step. Keep the other tenant unused except in step 10.

## 1. Meta token and permission verification

Confirm the Meta app id is set and the secret is stored as a secret, not in Git. On the accounts page, enter one long-lived Page token and the linked Instagram professional account id for a Page the business owns.

**Stop.** Do not press Verify until an operator approves this token check. Verify reads `debug_token` only. It records granted and missing permissions, token expiry, and data-access expiry. Expected permissions: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `read_insights`, `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`. A missing permission leaves the account unverified and publishes nothing.

## 2. Facebook and Instagram historical content import

**Stop.** Import runs only after step 1 shows the token is valid and an operator approves a read of recent posts. The import stores captions and themes Meta returned. It does not publish, follow, or like.

## 3. Read-only organic insights

Set `SOCIAL_GROWTH_INSIGHTS_MODE=live` only for this check, with `SOCIAL_GROWTH_PUBLISH_MODE` still `disabled`.

**Stop.** Approve one insights read for the account from step 1. Readings store the period, retrieval time, endpoint, and `META_GRAPH_API_VERSION`. A missing value stays null. Fixture readings stay out of the live totals. Turn insights mode back to `disabled` when the read is stored.

## 4. Read-only GA4 reporting

Connect a Google account with `analytics.readonly` and set the GA4 property id on the brand page.

**Stop.** Approve one `GA4_MODE=live` read for a short date range. Sessions, users, and key events stay separate from clicks and enquiries. Turn `GA4_MODE` back to `disabled` afterwards.

## 5. One approved Facebook publication

Needs `ENABLE_SOCIAL_GROWTH` on, an approved strategy and creative, a grant or an inbox approval for that creative, an authorized scope that includes `social.publish`, and `SOCIAL_GROWTH_PUBLISH_MODE=live`.

**Stop.** Approve one Facebook image post. Confirm one provider post id and permalink, one external effect, and no second post when the scheduler runs again. Set publish mode back to `disabled`.

## 6. One approved Instagram image publication

Same gates as step 5. The image URL must be the public `https` media address.

**Stop.** Approve one Instagram image. Confirm the container id, the published media id, and the permalink. Confirm a second tick does not create another container.

## 7. One approved Instagram Reel

**Stop.** Approve one Reel that already passed the 9:16 checks. Confirm the upload finishes once and the permalink is stored. A processing result waits. It does not upload the file again while the effect is still in progress.

## 8. Tracking link to enquiry to CRM attribution

Use the tracking link from the published post. Open it in a normal browser, submit the capture form, and confirm the lead's first touch is that link when the lead had no earlier touch. A link-preview crawler is not an enquiry. This step uses the public form. It does not send email.

## 9. Scheduled publication and duplicate prevention

**Stop.** Approve one scheduled slot in the account's posting window. After it publishes, run the scheduler again. The second run publishes nothing for that slot. An unknown result stays unknown until reconciliation finds the post or an operator marks it not published, which is the only path to a new attempt.

## 10. Two-tenant isolation and operational recovery

As the second workspace, list accounts, calendar items, publications, and leads. None of the first workspace's rows appear. A token from the first workspace is not listed.

Take a database dump. Restore it into a new database and point a throwaway API at that copy. Confirm the published post's provider id is still stored and that publish mode on the copy is disabled. Drop the throwaway database. Do not restore over the demonstration database.
