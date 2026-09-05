# Acquisition Engine

Phases 8–10.

**Phase 8 implemented:** inbound capture, consent/opt-out refusal, email and fuzzy-name dedupe review, mock intelligence providers.

**Phases 9–10 implemented:** campaigns/ABM desks and sequences that enroll into Approvals or tasks. Paid-ad spend is a ledger, not a live network. Embedding similarity merges remain later.

Still later: live ads/email providers, embedding similarity merges.

Lead capture stores source, channel, campaign, ad, creative, keyword, landing page, UTM, timestamp, consent, device.

Providers: `CompanyDataProvider`, `ContactDataProvider`, `IntentDataProvider`, `NewsProvider`, `TechnologyDataProvider` with mock adapters first.

Dedupe: deterministic email, domain, fuzzy company name. Uncertain merges require review. Phone and embedding similarity are not in this cut.

Lead score v1 (100): ICP 25, intent 20, engagement 20, persona 10, company potential 10, buying trigger 10, timing 5.

API: `/api/v1/acquisition/capture`, `/captures`, `/dedupe`, `/overview`.
UI: `/acquisition`.
