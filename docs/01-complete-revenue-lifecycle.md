# Complete Revenue Lifecycle

```mermaid
flowchart TD
  marketResearch[MarketResearch]
  opportunityDiscovery[OpportunityDiscovery]
  icp[ICPDiscovery]
  persona[PersonaDiscovery]
  targetAccounts[TargetAccounts]
  signals[BuyingSignals]
  committee[BuyingCommittee]
  campaign[CampaignStrategy]
  content[Content]
  ads[Advertising]
  capture[LeadCapture]
  outbound[Outbound]
  enrich[Enrichment]
  score[Scoring]
  qualify[Qualification]
  sdr[AISDR]
  meeting[Meeting]
  opp[Opportunity]
  proposal[Proposal]
  close[Close]
  onboard[Onboarding]
  health[Health]
  renew[Renewal]
  expand[Expansion]
  advocate[Advocacy]
  learn[LearningLoop]
  marketResearch --> opportunityDiscovery --> icp --> persona --> targetAccounts --> signals --> committee
  committee --> campaign --> content --> ads --> capture --> outbound --> enrich --> score --> qualify --> sdr
  sdr --> meeting --> opp --> proposal --> close --> onboard --> health --> renew --> expand --> advocate --> learn
  learn --> icp
```

## Stage inventory

Market research, opportunity discovery, ICP, persona, target accounts, buying signals, committee mapping, campaign, content, ads, social, landing pages, capture, outbound, enrichment, dedupe, intent, ICP score, lead score, qualification, AI SDR, multi-channel engagement, conversation, meeting, discovery, opportunity, solution, demo, technical discovery, business case, proposal, quote, approval, negotiation, procurement, legal, contract, close, onboarding, handoff, adoption, health, CS, QBR, upsell, cross-sell, renewal, expansion, advocacy, referral, learning.

Every stage is represented in the architecture. Implementation is phased. Closed Won must create Customer and Renewal stub records so post-sale modules are not blocked.
