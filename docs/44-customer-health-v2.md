# 44 — Customer Health rules-v2

One live `HealthScore` row per customer. The active ruleset is `rules-v2`. Snapshots keep `ruleset_version`. Trend and `customer.health_changed` compare only same-version snapshots.

Components: ONBOARDING, USAGE, ADOPTION, SUPPORT, ENGAGEMENT, COMMERCIAL, SUCCESS, RELATIONSHIP. Only `LIVE` + `SUFFICIENT` (fresh) enter the numeric denominator. MOCK, NOT_CONFIGURED, UNAVAILABLE, and STALE are excluded. `health_data_coverage` is eligible / defined and is shown separately from `total`.

Thresholds 50 and 70 stay on the reweighted 0–100 scale. The event fires on a threshold cross, a material component status change, or a risk-category change. Tiny noise inside the +4/−4 band does not page Autopilot.

Risk types: `ADOPTION_RISK`, `USAGE_DECLINE`, `SUPPORT_RISK`, `COMMERCIAL_RISK`, `RELATIONSHIP_RISK`, `RENEWAL_RISK`. Advocacy uses `advocacy-rules-v2` and is blocked when a critical ticket is open or coverage fails policy. Feature snapshots and outcome labels accumulate; `last_trained` stays null.
