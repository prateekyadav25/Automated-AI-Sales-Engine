# 56 — Automation ROI methodology

The OS does not claim “AI generated ₹X” or employee replacement.

## Human touch

Counted from persisted rows only:

- Manual email / call / meeting / task / note / stage change (`Activity.actor_type=human`)
- Approval decision (`approved` / `rejected` / `edited`)
- Manual CRM edits in audit (`opportunity.update`, `lead.update`, `customer.update`, `account.update`)

Page views are not touches.

Metrics: `human_touches_before_qualification`, `human_touches_before_close`, and later per-customer / per-renewal when enough rows exist. Empty samples stay null.

## Autonomous execution rate

```
automatable actions executed by the system / eligible actions
```

Eligible ≈ automated internal tasks + approvals + recorded manual overrides. This is not headcount reduction.

## AI-prepared pipeline

Uses lead `source` provenance (`ai_discovery` vs human / import / inbound / referral / campaign / partner).

Revenue line: “Revenue associated with AI-prepared opportunities” plus this methodology. Never “AI generated revenue.”

## Cost

Read `model_usage.estimated_cost` and persisted provider counters only. Missing usage rows mean cost is unknown, not zero invention. Autopilot fails closed when `ai_daily_budget` is set and estimated spend meets the cap.
