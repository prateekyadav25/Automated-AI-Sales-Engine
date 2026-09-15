# Customer Success Engine

Phases 16–17 plus Autopilot batch 3. **Implemented:** Closed Won activates the customer, a handoff package, an 8-milestone onboarding plan, a success plan, and a rules-v1 health score. Usage is a labeled mock provider and is excluded from the numeric total. Support and finance are UNAVAILABLE until connected. Risks use `churn-rules-v1`. CustomerSuccessAgent drafts only; send stays in Approvals.

Closed Won creates Customer and a handoff pack: objectives, solution, scope, commercials, stakeholders, risks, success criteria.

Health combines adoption, usage, engagement, support, sentiment, commercial/payment health, relationship, onboarding, outcomes, executive sponsorship.

CS agent: monitor health, risk, success plans, outreach drafts, meeting briefs, QBR drafts, escalations.

Providers: `ProductUsageProvider`, support adapters, finance adapters — never tight-coupled SDKs in domain services.
