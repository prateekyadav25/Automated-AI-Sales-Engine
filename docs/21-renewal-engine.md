# Renewal Engine

Phase 18. **Implemented as a desk over Closed Won renewal stubs.** GRR/NRR stay 1.0 until amendments exist.

Track contract start/end, notice, ARR, escalation, owner, probability, health, risk.

Lead times: 180 / 120 / 90 / 60 / 30 days.

MVP already inserts a `renewals` stub on Closed Won so this engine can attach later without a schema rewrite.

GRR, NRR, logo retention, churn ARR, contraction, expansion are computed deterministically from contracts and amendments when those tables exist.
