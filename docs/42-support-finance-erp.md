# 42 — Support, Finance, and ERP

Generic signed webhooks persist tickets and invoices by stable external id. Void/delete transitions status; history is not hard-deleted.

Support metrics: open, critical, 30-day count, average resolution, escalations, reopens. Sentiment is stored only when the payload includes it.

Finance persists outstanding balance, days past due, overdue count, and last payment date. Unknown currency or amount stays null. ARR is never invented. A finance/ERP value that disagrees with `Contract.total_value` opens a `COMMERCIAL_DATA_MISMATCH` task and does not overwrite contract terms.

Zendesk, Freshdesk, ServiceNow, and Stripe remain stub adapters that return `NOT_CONFIGURED` until credentials exist.
