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
  description: string;
  is_default: boolean;
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
  commercial_impact?: string;
  budget_impact?: string;
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
};

export type Campaign = {
  id: string;
  name: string;
  channel: string;
  status: string;
  objective: string;
  budget: string;
  spent: string;
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
};

export type ProviderHealth = {
  name: string;
  provider: string;
  is_mock: boolean;
  connected: boolean;
  reason: string;
  state: string;
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
};

export type Meeting = {
  id: string;
  title: string;
  summary: string;
  next_steps: string;
  account_id: string | null;
  opportunity_id: string | null;
  is_mock: boolean;
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
  account_name: string;
  renewal_date: string | null;
  current_arr: string;
  status: string;
};

export type Whitespace = {
  id: string;
  account_name: string;
  product_name: string;
  status: string;
  propensity: number;
  value_hint: string;
};

export type AdvocacyAsset = {
  id: string;
  account_id: string;
  kind: string;
  readiness: number;
  status: string;
  notes: string;
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
