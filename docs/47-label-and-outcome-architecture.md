# 47 — Label and outcome architecture

Labels are versioned. Changing logic requires a new `label_version`.

## LabelDefinition

Stored per tenant/task/version:

- definition
- horizon days
- positive condition
- negative condition
- censoring rule

## Statuses

| Status | Meaning | Class value |
|---|---|---|
| PENDING | Horizon not elapsed | not a label |
| CENSORED | Outcome cannot be known yet | not a label |
| POSITIVE | Definition met inside the horizon | 1 |
| NEGATIVE | Horizon elapsed without the positive event | 0 |

PENDING and CENSORED must never be trained as negatives.

`occurred_at` is event time, not write time.

## Initial labels

- LEAD_CONVERTED — `lead.qualified` (or `converted` status) within horizon
- OPPORTUNITY_WON — stage `closed_won` within horizon
- CLOSE_DATE_SLIPPED — `expected_close` moved later
- CUSTOMER_CHURNED — terminated / failed renewal
- CUSTOMER_RENEWED — renewal completed without churn
- CUSTOMER_EXPANDED — approved expansion opportunity won

Human recommendation feedback (`accepted` / `rejected` / `edited` / `ignored`) is stored in `recommendation_feedback`. It is a signal, not ground truth.
