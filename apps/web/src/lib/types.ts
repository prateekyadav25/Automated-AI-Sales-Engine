export type Account = {
  id: string;
  name: string;
  industry: string;
  website: string;
  domain: string;
  hq_country: string;
  employee_count: number | null;
  annual_revenue: string | null;
  ownership: string;
  target_tier: string;
  notes: string;
};

export type Contact = {
  id: string;
  account_id: string | null;
  account_name: string | null;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  seniority: string;
  department: string;
  buying_role: string;
  consent_email: boolean;
  opt_out: boolean;
  linkedin_url?: string;
  preferred_channel?: string;
  consent_voice?: boolean;
};

export type LeadScore = {
  total: number;
  icp_fit: number;
  intent: number;
  engagement: number;
  persona: number;
  company_potential: number;
  buying_trigger: number;
  timing: number;
  reasons: string;
  version: string;
  confidence: number;
};

export type Lead = {
  id: string;
  account_id: string | null;
  first_name: string;
  last_name: string;
  email: string;
  company_name: string;
  title: string;
  status: string;
  source: string;
  channel: string;
  consent_email: boolean;
  opt_out: boolean;
  intent_score: number;
  engagement_score: number;
  has_buying_trigger: boolean;
  notes: string;
  latest_score: LeadScore | null;
  owner_id?: string | null;
  owner_name?: string;
  operating_plan_id?: string | null;
  icp_id?: string | null;
  product_name?: string;
  offer_label?: string;
  enrichment_state?: string;
  missing_information?: string;
  eligibility?: string;
  next_action?: string;
  approval_id?: string;
  native_platform?: string;
  native_form_id?: string;
  native_status?: string;
  native_product?: string;
  native_permission?: string;
  native_attribution?: string;
  native_missing?: string;
  native_acknowledgement?: string;
  native_review?: string;
};

export type Opportunity = {
  id: string;
  account_id: string;
  name: string;
  stage: string;
  amount: string;
  probability: number;
  next_step: string;
  expected_close: string | null;
  loss_reason?: string;
};

export type Task = {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  due_at: string | null;
  source: string;
  entity_type: string;
  entity_id: string;
  owner_name?: string;
};

export type Activity = {
  id: string;
  title: string;
  body: string;
  activity_type: string;
  actor_type: string;
  created_at: string;
};

export type ICP = {
  id: string;
  name: string;
  industries: string;
  geographies: string;
  min_employees: number | null;
  max_employees?: number | null;
  description: string;
  is_default: boolean;
  personas?: string;
  seniorities?: string;
  job_functions?: string;
  target_companies?: string;
  keywords?: string;
};

export type KPIs = {
  total_leads: number;
  mql_count: number;
  sql_count: number;
  total_accounts: number;
  open_opportunities: number;
  won_opportunities: number;
  open_pipeline_value: string;
  weighted_pipeline_value: string;
  win_rate: number;
  tasks_open: number;
  tasks_overdue: number;
  pending_approvals: number;
  knowledge_sources: number;
};

export type LifecyclePulse = {
  campaigns: number;
  sequences: number;
  enrollments: number;
  conversations: number;
  meetings: number;
  open_quotes: number;
  at_risk_deals: number;
  customers: number;
  at_risk_health: number;
  renewals_due_90: number;
  whitespace: number;
  advocacy: number;
  playbook_runs: number;
  arr: string;
  note: string;
};

export type Overview = {
  kpis: KPIs;
  pipeline_by_stage: { stage: string; count: number; amount: string }[];
  recent_activities: Activity[];
  overdue_tasks: Task[];
  at_risk_opportunities: Opportunity[];
  lifecycle?: LifecyclePulse;
};

export type Approval = {
  id: string;
  action_level: number;
  action_type: string;
  title: string;
  status: string;
  payload_json?: string;
  decision_note?: string;
  run_id?: string | null;
  entity_type?: string;
  entity_id?: string;
  who?: string;
  why?: string;
  evidence?: string;
  risk?: string;
  expected_outcome?: string;
  message?: string;
  subject?: string;
  product_name?: string;
  generation?: string;
  context_version?: string;
  personalisation?: string;
  missing_information?: string;
  eligibility?: string;
  next_action?: string;
  commercial_impact?: string;
  budget_impact?: string;
  category?: string;
};

export type SearchHit = {
  entity_type: string;
  id: string;
  title: string;
  subtitle: string;
};

export type AccountContext = {
  account: Account;
  contacts: Contact[];
  opportunities: Opportunity[];
  tasks: Task[];
};

export type Customer = {
  id: string;
  account_id: string;
  opportunity_id: string | null;
  status: string;
  arr: string;
  account_name?: string | null;
  lifecycle_state?: string;
  owner_id?: string | null;
  csm_owner_id?: string | null;
  health_trend?: string;
  qbr_cadence?: string;
  next_qbr_at?: string | null;
  churn_reason?: string;
};

export type CampaignEnquiry = {
  capture_id: string;
  lead_id: string;
  status: string;
  first_touch: boolean;
};

export type Campaign = {
  id: string;
  name: string;
  channel: string;
  status: string;
  objective: string;
  budget: string;
  spent: string;
  start_date?: string | null;
  end_date?: string | null;
  external_campaign_id?: string;
  provider?: string;
  provider_status?: string;
  impressions?: number;
  clicks?: number;
  conversions?: number;
  ctr?: string | null;
  cpc?: string | null;
  cpl?: string | null;
  last_synced_at?: string | null;
  operating_plan_id?: string | null;
  creative_version_id?: string | null;
  audience?: string;
  geography?: string;
  placements?: string;
  timezone?: string;
  currency?: string;
  headline?: string;
  body?: string;
  call_to_action?: string;
  asset_ref?: string;
  destination?: string;
  assembly_status?: string;
  assembly_blocker?: string;
  offer_label?: string;
  live_execution_ready?: boolean;
  live_execution_note?: string;
  activated?: boolean;
  destination_url?: string;
  schedule_label?: string;
  ad_set_external_id?: string;
  creative_external_id?: string;
  ad_external_id?: string;
  ad_set_status?: string;
  creative_status?: string;
  ad_status?: string;
  enquiries?: CampaignEnquiry[];
};

export type DiscoveryRun = {
  created: number;
  skipped: Record<string, number>;
  lead_ids: string[];
  provider: string;
  is_mock: boolean;
  connected: boolean;
  reason: string;
  candidate_count: number;
  icp_name: string;
};

export type AutonomyStep = {
  id: string;
  name: string;
  position: number;
  status: string;
  detail_json: string;
};

export type AutonomyRun = {
  id: string;
  status: string;
  trigger: string;
  workflow?: string;
  summary: string;
  created_at: string;
  finished_at: string | null;
  steps: AutonomyStep[];
};

export type AutopilotSettings = {
  id: string;
  enabled: boolean;
  emergency_stop?: boolean;
  email_channel_paused?: boolean;
  ads_channel_paused?: boolean;
  voice_channel_paused?: boolean;
  discovery_channel_paused?: boolean;
  discovery_enabled: boolean;
  enrichment_enabled: boolean;
  lead_scoring_enabled: boolean;
  qualification_enabled: boolean;
  research_enabled: boolean;
  sequence_enrollment_enabled: boolean;
  outreach_preparation_enabled: boolean;
  max_leads_per_day: number;
  minimum_lead_score: number;
  timezone: string;
  quiet_hours_start: string;
  quiet_hours_end: string;
  customer_health_enabled?: boolean;
  renewal_enabled?: boolean;
  expansion_enabled?: boolean;
  advocacy_enabled?: boolean;
  customer_success_enabled?: boolean;
  qbr_automation_enabled?: boolean;
  upsell_enabled?: boolean;
  cross_sell_enabled?: boolean;
  expansion_auto_opportunity_enabled?: boolean;
};

export type ProviderHealth = {
  name: string;
  provider: string;
  is_mock: boolean;
  connected: boolean;
  reason: string;
  state: string;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  last_error_summary?: string;
  mode?: string;
  pending_actions?: number;
  failed_actions?: number;
};

export type ProviderAction = {
  id: string;
  action_type: string;
  provider: string;
  status: string;
  failure_class?: string;
  external_id?: string;
  entity_type?: string;
  entity_id?: string;
  last_error?: string;
  attempts?: number;
  request_summary?: string;
  created_at: string;
  updated_at?: string | null;
  next_retry_at?: string | null;
};

export type AutonomyToday = {
  targets_discovered: number;
  leads_enriched: number;
  leads_scored: number;
  leads_qualified: number;
  research_completed: number;
  messages_prepared: number;
  approvals_waiting: number;
  meetings_booked: number;
  opportunities_created: number;
  customers_at_risk: number;
  renewals_processed: number;
  expansion_opportunities: number;
};

export type AutonomyStatus = {
  enabled: boolean;
  last_cycle_at: string | null;
  next_cycle_at: string | null;
  worker: string;
  queue: string;
  today: AutonomyToday;
  providers: ProviderHealth[];
  blocked_human: number;
  blocked_config: string[];
  blocked_policy: number;
  failed_steps: number;
  pending_actions?: number;
  dead_letters?: number;
  alerts?: string[];
  scheduler_unhealthy?: boolean;
};

export type AutonomyActivity = {
  id: string;
  occurred_at: string;
  kind: string;
  title: string;
  entity_type: string;
  entity_id: string;
  status?: string;
};

export type EntityAutomation = {
  entity_type: string;
  entity_id: string;
  state: string;
  last_action: string;
  next_action: string;
  blocked_reason: string;
  paused: boolean;
  run_id: string | null;
  workflow: string;
  run_status: string;
};

export type Sequence = {
  id: string;
  name: string;
  channel: string;
  status: string;
  purpose: string;
};

export type Enrollment = {
  id: string;
  sequence_id: string;
  lead_id: string;
  status: string;
  current_step: number;
};

export type EmailMessage = {
  id: string;
  direction: string;
  from_addr: string;
  subject: string;
  body_text: string;
  provider: string;
  status: string;
  classification: string;
  created_at: string;
};

export type Conversation = {
  id: string;
  channel: string;
  subject: string;
  status: string;
  sentiment: string;
  consent: boolean;
  provider: string;
  is_mock: boolean;
  summary: string;
  transcript?: string;
  lead_id?: string | null;
  provider_thread_id?: string;
  messages?: EmailMessage[];
  voice?: VoiceHandoff | null;
};

export type VoiceHandoff = {
  session_id: string;
  purpose: string;
  product_name: string;
  permission_source: string;
  permission_channel: string;
  permission_scope: string;
  permission_at: string;
  execution_authorized: boolean;
  owner_name: string;
  recipient: string;
  caller_identity: string;
  window_start: string;
  window_end: string;
  status: string;
  attempt_count: number;
  provider_call_id: string;
  fixture: boolean;
  outcome: string;
  last_event: string;
  blocker: string;
  recording: string;
  transcript: string;
  handoff_task_id: string;
  meeting_id: string;
  transfer: string;
  live_execution_ready: boolean;
  next_action: string;
};

export type MeetingSlot = {
  start: string;
  end: string;
  owner_timezone: string;
  attendee_timezone: string;
  owner_local: string;
  attendee_local: string;
};

export type Meeting = {
  id: string;
  title: string;
  summary: string;
  next_steps: string;
  account_id: string | null;
  opportunity_id: string | null;
  is_mock: boolean;
  provider?: string;
  status?: string;
  start_at?: string | null;
  end_at?: string | null;
  timezone?: string;
  calendar_account?: string;
  recording_consent?: boolean;
  transcript?: string;
  insights_json?: string;
  lead_id?: string | null;
  purpose?: string;
  lead_name?: string;
  enquiry_note?: string;
  product_name?: string;
  offer_label?: string;
  owner_name?: string;
  calendar_id?: string;
  owner_timezone?: string;
  attendee_timezone?: string;
  slots?: MeetingSlot[];
  selected_slot?: MeetingSlot | null;
  booking_authorized?: boolean;
  invite_authorized?: boolean;
  conference_status?: string;
  conference_id?: string;
  join_url?: string;
  fixture_join_url?: string;
  fixture?: boolean;
  blocker?: string;
  last_synced_at?: string | null;
  live_execution_ready?: boolean;
  attendance?: string;
  next_action?: string;
  captures?: { id: string; provider: string; status: string; last_error: string; meeting_url: string }[];
};

export type DealInsight = {
  id: string;
  opportunity_id: string;
  opportunity_name: string;
  risk_score: number;
  reasons: string;
  version: string;
  missing_buyer: boolean;
  stall: boolean;
  close_slip: boolean;
};

export type Product = {
  id: string;
  sku: string;
  name: string;
  list_price: string;
};

export type Quote = {
  id: string;
  opportunity_id: string;
  status: string;
  discount_pct: number;
  tax_pct: number;
  subtotal: string;
  total: string;
  approval_required: boolean;
  version?: number;
  terms?: string;
  currency?: string;
  customer_facing_name?: string;
  offer_label?: string;
  sku?: string;
  scope_text?: string;
  billing_cadence?: string;
  service_start?: string | null;
  service_end?: string | null;
  valid_until?: string | null;
  parent_quote_id?: string | null;
  superseded_by_id?: string | null;
  context_version?: string;
  fixture?: boolean;
  lines?: { id: string; quantity: number; unit_price: string; line_total: string; customer_facing_name?: string; offer_label?: string; sku?: string }[];
};

export type CommercialClose = {
  opportunity_id: string;
  account_id: string;
  stage: string;
  quote_id: string | null;
  quote_version: number | null;
  quote_status: string;
  currency: string;
  subtotal: string;
  total: string;
  discount_pct: number | null;
  tax_pct: number | null;
  customer_facing_name: string;
  offer_label: string;
  sku: string;
  scope_text: string;
  terms: string;
  billing_cadence: string;
  service_start: string | null;
  service_end: string | null;
  valid_until: string | null;
  acceptance_source: string;
  acceptance_review: string;
  acceptance_relationship: string;
  acceptance_evidence: string;
  provider_verified: boolean;
  blockers: string[];
  ready: boolean;
  won: boolean;
  purchase_status: string;
  payment_status: string;
  customer_id: string | null;
  customer_status: string;
  activated: boolean;
  onboarding_plan_id: string | null;
  onboarding_status: string;
  onboarding_next_action: string;
  onboarding_blocker: string;
  task_id: string | null;
  task_status: string;
  owner_id: string | null;
  owner_name: string;
  missing_information: string[];
  fixture: boolean;
  external_block: string;
  external_released: boolean;
  decided_at: string | null;
  reversal_reason: string;
  note: string;
};

export type PurchaseRecord = {
  id: string;
  opportunity_id: string;
  quote_id: string;
  quote_version: number | null;
  status: string;
  currency: string;
  amount: string;
  payment_status: string;
  customer_facing_name: string;
  sku: string;
  offer_label: string;
  scope_text: string;
  onboarding_status: string;
  onboarding_next_action: string;
  task_status: string;
  owner_name?: string;
  fixture: boolean;
  activated: boolean;
};

export type Forecast = {
  id: string;
  period: string;
  committed: string;
  best_case: string;
  pipeline: string;
  weighted: string;
  win_rate: number;
  version: string;
};

export type Health = {
  id: string;
  total: number;
  reasons: string;
  version: string;
  unavailable_components?: string;
  trend?: string;
  data_freshness?: string;
  health_data_coverage?: number;
};

export type SuccessRow = {
  id?: string;
  customer: Customer;
  account_id: string;
  account_name: string;
  health: Health | null;
  onboarding_status: string;
  renewal_date: string | null;
  arr: string;
};

export type RenewalRow = {
  id: string;
  customer_id?: string;
  account_name: string;
  renewal_date: string | null;
  current_arr: string;
  status: string;
  readiness?: number;
  recommended_action?: string;
  baseline_amount?: string | null;
  baseline_status?: string;
  stage?: string;
  why_ready?: string[];
  why_at_risk?: string[];
};

export type Whitespace = {
  id: string;
  account_name: string;
  product_name: string;
  status: string;
  propensity: number;
  value_hint: string;
};

export type ExpansionRec = {
  id: string;
  customer_id: string;
  account_id: string;
  kind: string;
  title: string;
  reason: string;
  confidence: number;
  amount: string | null;
  status: string;
  opportunity_id: string | null;
  outcome_status?: string;
  outcome_value?: string | null;
  outcome_product?: string;
};

export type AdvocacyAsset = {
  id: string;
  account_id: string;
  kind: string;
  readiness: number;
  status: string;
  notes: string;
  customer_id?: string | null;
  advocacy_type?: string;
  eligibility_score?: number;
  quote?: string | null;
};

export type PostSaleAttention = {
  customers_requiring_attention: number;
  onboarding_at_risk: number;
  renewals_approaching: number;
  renewals_at_risk: number;
  expansion_opportunities: number;
  advocacy_candidates: number;
  usage_risk?: number;
  support_risk?: number;
  commercial_risk?: number;
  high_utilization_candidates?: number;
};

export type LifecycleLane = {
  lane: string;
  running: number;
  waiting: number;
  blocked: number;
  completed_today: number;
  failed: number;
};

export type CustomerRisk = {
  id: string;
  risk_type: string;
  severity: string;
  summary: string;
  status: string;
};

export type Customer360 = {
  customer: Customer;
  account_name: string;
  lifecycle_state: string;
  health_total: number | null;
  health_trend: string;
  health_version: string;
  health_data_coverage?: number;
  health_components?: Record<string, { status?: string; score?: number | null; evidence?: string }>;
  unavailable_components: string;
  usage_freshness?: string;
  support_freshness?: string;
  finance_freshness?: string;
  commercial_freshness?: string;
  last_usage_at?: string | null;
  last_support_at?: string | null;
  last_finance_at?: string | null;
  support_open_critical?: number | null;
  finance_outstanding?: string | null;
  renewal_why_ready?: string[];
  renewal_why_at_risk?: string[];
  risks: CustomerRisk[];
  renewal_date: string | null;
  renewal_readiness: number;
  renewal_countdown_days: number | null;
  contract: { id: string; status: string; total_value: string | null; term_months: number | null; escalation_pct: number | null } | null;
  handoff: { id: string; status: string; kickoff_agenda: string; missing_fields: string[] } | null;
  onboarding_status: string;
  milestones: { id: string; title: string; status: string; due_date: string | null }[];
  usage: { provider: string; is_mock: boolean; evidence: string; trend: string } | null;
  expansion: ExpansionRec[];
  advocacy: { id: string; type: string; status: string; score: number; quote: string | null }[];
  automation: EntityAutomation;
  timeline: { occurred_at: string; kind: string; title: string; entity_type: string; source: string }[];
  time_to_value: {
    days_to_kickoff: number | null;
    days_to_go_live: number | null;
    days_to_first_value: number | null;
    days_to_onboarding_complete: number | null;
  };
  purchases?: PurchaseRecord[];
};

export type Referral = {
  id: string;
  referrer_account_id: string;
  referred_name: string;
  email: string;
  status: string;
};

export type ModelCard = {
  id: string;
  name: string;
  purpose: string;
  version: string;
  status: string;
  notes: string;
  last_trained?: string | null;
  task_key?: string;
  algorithm?: string;
  dataset_version?: string;
  metrics_json?: string | null;
  limitations?: string;
};

export type Readiness = {
  task_key: string;
  name: string;
  entity_type: string;
  status: string;
  recommended_status: string;
  reason: string;
  rows: number;
  mature_labels: number;
  positive: number;
  negative: number;
  pending: number;
  censored: number;
  history_days: number;
  minimum_rows: number;
  minimum_positive: number;
  minimum_negative: number;
  minimum_history_days: number;
  feature_set_version: string;
  label_version: string;
  horizon_days: number;
  baseline: string;
  split_policy: string;
};

export type DatasetVersion = {
  id: string;
  task_key: string;
  version: string;
  feature_set_version: string;
  label_version: string;
  row_count: number;
  positive_count: number;
  negative_count: number;
  censored_count: number;
  scope: string;
  fingerprint: string;
  status: string;
};

export type ModelVersion = {
  id: string;
  task_key: string;
  version: string;
  algorithm: string;
  feature_set_version: string;
  label_version: string;
  dataset_version: string;
  status: string;
  metrics_json: string | null;
  training_completed_at: string | null;
  is_rules: number;
  artifact_location: string;
};

export type Playbook = {
  id: string;
  name: string;
  trigger_event: string;
  autonomy_level: number;
  is_active: boolean;
};

export type WorkflowRun = {
  id: string;
  trigger_event: string;
  status: string;
  log_json: string;
  finished_at: string | null;
};

export type AccountLifecycle = {
  meetings: Meeting[];
  quotes: Quote[];
  insights: DealInsight[];
  whitespace: Whitespace[];
  advocacy: AdvocacyAsset[];
  customer: Customer | null;
  health: Health | null;
  renewal: RenewalRow | null;
};

export type Team = {
  id: string;
  name: string;
  team_type: string;
};

export type Territory = {
  id: string;
  name: string;
  region: string;
};

export type ImportPreview = {
  entity: string;
  columns: string[];
  rows: Record<string, string>[];
  errors: string[];
  count: number;
};

export type ChatResponse = {
  reply: string;
  is_mock: boolean;
  provider: string;
  citations?: { title: string; text: string; score: number }[];
};

export type Market = {
  id: string;
  name: string;
  industry: string;
  geography: string;
  description: string;
  attractiveness: number;
  ai_readiness: number;
  technology_readiness: number;
  budget_potential: number;
  growth_potential: number;
  competitive_intensity: number;
  procurement_probability: number;
  buying_timing: number;
  score_reasons: string;
  score_version: string;
};

export type IntelligenceSignal = {
  id: string;
  kind: string;
  title: string;
  source: string;
  evidence: string;
  confidence: number;
  impact: string;
  recommended_action: string;
  occurred_at: string | null;
  is_mock: boolean;
  account_id?: string | null;
  market_id?: string | null;
};

export type TriggerEvent = {
  id: string;
  account_id: string | null;
  trigger_type: string;
  title: string;
  body: string;
  source: string;
  confidence: number;
  recommended_action: string;
  occurred_at: string | null;
  is_mock: boolean;
};

export type InboundCapture = {
  id: string;
  lead_id: string | null;
  email: string;
  company_name: string;
  source: string;
  channel: string;
  campaign: string;
  status: string;
  consent_email: boolean;
  captured_at: string | null;
};

export type DedupeReview = {
  id: string;
  left_type: string;
  left_id: string;
  right_type: string;
  right_id: string;
  match_kind: string;
  confidence: number;
  reason: string;
  status: string;
};
