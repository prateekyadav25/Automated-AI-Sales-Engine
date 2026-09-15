# Renewal Engine

Phase 18 plus Autopilot batch 3. **Implemented:** Closed Won mints a Contract (when evidence exists) and a renewal record. Autopilot opens windows at 180/120/90/60/30 days without duplicates. Readiness is `rules-v1`. Commercial baseline is copied from the contract and stays `needs_review` when escalation is unknown. RenewalAgent drafts; `renewal.commercial` stays in Approvals. GRR/NRR stay 1.0 until amendments exist.

Track contract start/end, notice, ARR, escalation, owner, probability, health, risk.

Lead times: 180 / 120 / 90 / 60 / 30 days.

MVP already inserts a `renewals` stub on Closed Won so this engine can attach later without a schema rewrite.

GRR, NRR, logo retention, churn ARR, contraction, expansion are computed deterministically from contracts and amendments when those tables exist.
