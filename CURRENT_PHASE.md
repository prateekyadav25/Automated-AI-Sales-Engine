# Current Phase

**Phases 0–22 plus Autopilot control plane batch 1 are in product.**

Honest limits that stay in force:

- Autopilot is event-driven plus a reconcile beat. Enable Autopilot is the operating switch; Run now only accelerates.
- Approved email writes a MockEmailProvider message id and activity. No live Gmail or reply ingest.
- Discovered leads stay without email consent. Outreach approvals require consent; otherwise Autopilot shows Blocked by policy.
- Mock discovery invents no people. Targets appear only from Apify dataset items, inbound/manual/import, or existing records.
- Ads launch queues `ads.spend`. Live LinkedIn/Meta only with keys. No invented CTR.
- Dial requires consent + Approval. Live Twilio/Vapi only with keys.
- Calendar, Postgres RLS, pgvector, MinIO cutover, and post-sale autopilot are later batches.
- Phase 21: rules-v1 model cards. `last_trained` is null. No invented accuracy.

Next authorized work: live Gmail/Calendar, vendor keys for ads/voice, or `harvestapi/linkedin-profile-search` for ICP hunting.
