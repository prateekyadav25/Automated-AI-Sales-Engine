import { api } from "@agrayian/sdk";

export const GROWTH_API = "/api/v1/social-growth";

export type Provenance = "live" | "fixture" | "operator" | "mock" | "website" | "rendered" | "model_generated" | "operator_upload" | string;

export type GrowthAccount = {
  id: string;
  platform: "facebook" | "instagram";
  external_id: string;
  page_id: string;
  name: string;
  username: string;
  provenance: string;
  status: string;
  token_expires_at: string;
  data_access_expires_at: string;
  granted_scopes: string[];
  missing_scopes: string[];
  capabilities: Record<string, boolean | string | null>;
  last_verified_at: string;
  last_error: string;
  timezone: string;
  posting_windows: { days: number[]; start: string; end: string }[];
  daily_cap: number;
  api_version: string;
  followers_count: number | null;
  followers_observed_at: string;
  problem: string;
  publish_eligible: boolean;
  insights_eligible: boolean;
  reconnect_required: boolean;
  posting_limit: string;
};

export type DeploymentPreflight = {
  status: "blocked" | "awaiting_authorization";
  publish_mode: string;
  insights_mode: string;
  ga4_mode: string;
  ads_mode: string;
  public_api_base_url: string;
  https_media: boolean;
  meta_app_configured: boolean;
  dedicated_token_key: boolean;
  blockers: string[];
};

export type AcceptanceStep = {
  step_key: string;
  title: string;
  status: "not_started" | "blocked" | "awaiting_authorization" | "verified_live" | "failed" | "not_supported";
  reason: string;
  authorized_at: string;
  note: string;
};

export type BrandFact = {
  id: string;
  category: string;
  statement: string;
  value: string;
  source_url: string;
  source_id: string;
  evidence: string;
  observed_at: string;
  method: string;
  state: "extracted" | "needs_review" | "approved" | "rejected" | string;
  confidence: number;
  reviewed_at: string;
  review_note: string;
};

export type GrowthAsset = {
  id: string;
  role: string;
  position: number;
  mime: string;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  size_bytes: number;
  template: string;
  provenance: string;
  model_id: string;
  quality_state: string;
  quality: { state?: string; checks?: { name: string; ok: boolean; detail: string }[] };
  preview_url: string;
  public_media_ready: boolean;
  commercial: boolean;
};

export type BrandView = {
  status: string;
  profile: null | {
    id: string;
    website_url: string;
    company_name: string;
    last_analysis_at: string;
    analysis: Record<string, unknown>;
    palette: { hex: string; source: string; url?: string }[];
    voice: Record<string, unknown>;
    logo: GrowthAsset | null;
    competitor_usernames: string[];
  };
  facts: BrandFact[];
  counts: Record<string, Record<string, number>>;
  sources: { id: string; kind: string; url: string; title: string; status: string; http_status: number | null; fetched_at: string; provenance: string }[];
  competitors: {
    id: string;
    username: string;
    status: string;
    followers_count: number | null;
    media_count: number | null;
    sample_size: number | null;
    posts_per_week: string | null;
    avg_likes: string | null;
    avg_comments: string | null;
    retrieved_at: string;
    provenance: string;
    error: string;
  }[];
  history: { account_id: string; origin: string; posts: number; oldest: string; newest: string }[];
};

export type Pillar = { key: string; name: string; description: string; fact_ids: string[] };

export type Strategy = {
  id: string;
  version: number;
  status: string;
  objective: string;
  optimization_metric: string;
  pillars: Pillar[];
  audiences: string[];
  cadence: Record<string, { posts_per_week: number; formats: Record<string, number> }>;
  call_to_action: string;
  destination_kind: string;
  destination_form_key_id: string;
  destination_url: string;
  auto_create: boolean;
  auto_schedule: boolean;
  review_terms: string[];
  horizon_days: number;
  approved_at: string;
  content_hash: string;
};

export type BusinessEvent = { id: string; title: string; kind: string; starts_on: string; ends_on: string; details: string; fact_ids: string[]; source_url: string; status: string };

export type StrategyView = {
  active: Strategy | null;
  draft: Strategy | null;
  suggested_pillars: Pillar[];
  forms: { id: string; name: string }[];
  events: BusinessEvent[];
  review_terms_default: string[];
};

export type Brief = {
  pillar?: { key: string; name: string };
  facts?: { id: string; category: string; statement: string; source_url: string }[];
  format?: string;
  audience?: string;
  call_to_action?: string;
  repetition?: { max_similarity: number; threshold: number; passed: boolean; note?: string };
  prior_content?: { id: string; kind: string; similarity: number }[];
  performance?: { metric: string; provider_metric: string; verdict: string; rule: string; pillar?: { mean: number; sample: number } | null };
  event?: { id: string; title: string; kind: string; starts_on: string; ends_on: string } | null;
  rationale?: string;
  strategy_version?: number;
};

export type CalendarItem = {
  id: string;
  account_id: string;
  account_name: string;
  platform: string;
  account_provenance: string;
  planned_for: string;
  local_date: string;
  pillar_key: string;
  format: string;
  status: string;
  blocker: string;
  brief: Brief;
  creative: { id: string; status: string; version: number; quality_state: string } | null;
  publication: { id: string; status: string; external_id: string; permalink: string; provenance: string; last_error: string } | null;
};

export type Creative = {
  id: string;
  item_id: string;
  account: { id: string; platform: string; name: string; provenance: string } | null;
  version: number;
  format: string;
  title: string;
  caption: string;
  hashtags: string[];
  alt_text: string;
  call_to_action: string;
  link_url: string;
  fact_ids: string[];
  claims: { unsupported?: string[]; sensitive?: string[]; checked?: { token: string; supported: boolean }[] };
  generation: string;
  model_id: string;
  status: string;
  review_reasons: string[];
  quality_state: string;
  quality: { caption?: { state: string; checks: { name: string; ok: boolean; detail: string }[] }; generation_notes?: string[] };
  content_hash: string;
  approved_at: string;
  review_note: string;
  planned_for: string;
  item_status: string;
  brief: Brief;
  assets: GrowthAsset[];
};

export type Grant = { id: string; name: string; platform: string; mode: string; volume_cap: number; status: string; expires_at: string; published_last_24h: number };

export type Recommendation = { id: string; kind: string; observation: string; evidence: Record<string, unknown>; sample_size: number; limitation: string; proposed_change: string; verdict: string; created_at: string };

export type Overview = {
  generated_at: string;
  flag_enabled: boolean;
  operating_mode: string;
  demo_scope: { status: string; expires_at: string } | null;
  brand: { status: string; website_url: string; company_name: string; last_analysis_at: string; facts: Record<string, number>; claims_waiting: number };
  accounts: GrowthAccount[];
  strategy: Strategy | null;
  draft_strategy: Strategy | null;
  calendar: { next_7_days: number; next_30_days_by_status: Record<string, number> };
  review_queue: number;
  publications: Record<string, number>;
  attribution_30d: { first_party_clicks: number; enquiries: number; qualified_leads: number; won_purchases: number; ga4_status: string };
  automation: {
    capabilities: {
      image_rendering: { ready: boolean; detail: string };
      video_rendering: { ready: boolean; detail: string };
      model_imagery: { ready: boolean; detail: string };
      graph_api_version: string;
      publish_mode: string;
      insights_mode: string;
      ga4_mode: string;
      brand_fetch_mode: string;
      public_media_base: string;
      public_media_ready: boolean;
    };
    grants: Grant[];
    runs: { id: string; status: string; trigger: string; kind: string; summary: string; created_at: string }[];
    blocked: { id: string; status: string; planned_for: string; blocker: string }[];
  };
  recommendations: Recommendation[];
  accounts_needing_attention: GrowthAccount[];
  live_publication_count: number;
  account_count: number;
};

export type MetricRow = { metric: string; value: number | null; aggregation: string; coverage_days: number; range_days: number; partial?: boolean; retrieved_at?: string; statuses: Record<string, number>; error?: string };

export type PerformanceView = {
  range: { start: string; end: string };
  note: string;
  accounts: {
    account: { id: string; platform: string; name: string; provenance: string; status: string };
    evidence: "live" | "fixture";
    account_metrics: { metrics: MetricRow[] };
    media: {
      posts: { id: string; external_id: string; origin: string; format: string; pillar_key: string; posted_at: string; permalink: string; caption: string; metrics: Record<string, number | null>; statuses: Record<string, string>; retrieved_at: string; measured: boolean }[];
      totals: { metric: string; sum: number | null; posts_with_value: number; posts_without_value: number }[];
      unmeasured_posts: number;
    };
  }[];
};

export type AttributionView = {
  range: { start: string; end: string };
  traffic: {
    first_party_clicks: number;
    bot_clicks_excluded: number;
    definition: string;
    ga4: { status: string; detail?: string; property_id?: string; coverage_days?: number; range_days?: number; retrieved_at?: string; note?: string; rows: { source: string; medium: string; campaign: string; sessions: number | null; total_users_daily_sum: number | null; key_events: number | null }[] };
  };
  enquiries: { count: number; leads: number; definition: string };
  qualified_leads: { count: number; definition: string };
  sales: { won_purchases: number; amounts: Record<string, string>; fixture_amounts: Record<string, string>; definition: string };
};

export type Publication = { id: string; item_id: string; creative_id: string; account_id: string; platform: string; format: string; status: string; container_id: string; external_id: string; permalink: string; published_at: string; attempts: number; failure_class: string; last_error: string; next_attempt_at: string; api_version: string; provenance: string };

export const RANGES = ["1d", "7d", "30d", "90d", "custom"] as const;
export type RangeKey = (typeof RANGES)[number];

export async function growth<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await api<T>(`${GROWTH_API}${path}`, init);
  return response.data as T;
}

export function send(body: unknown, method = "POST"): RequestInit {
  return { method, body: JSON.stringify(body ?? {}) };
}

export function metricText(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Unavailable";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function coverageText(row: Pick<MetricRow, "coverage_days" | "range_days" | "value">): string {
  if (row.value === null) return "No reading";
  return row.coverage_days >= row.range_days ? `${row.coverage_days} of ${row.range_days} days` : `Partial: ${row.coverage_days} of ${row.range_days} days`;
}

export function provenanceLabel(value: string): string {
  const labels: Record<string, string> = {
    live: "Live provider",
    fixture: "Fixture (not live)",
    operator: "Operator recorded",
    mock: "Mock",
    website: "From the website",
    rendered: "Rendered template",
    model_generated: "Model background",
    operator_upload: "Uploaded",
    provider: "Provider",
    deterministic: "Deterministic",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

export type Tone = "neutral" | "gold" | "mint" | "rose" | "ok" | "blue";

export function statusTone(status: string): Tone {
  if (["approved", "published", "connected", "passed", "recorded", "analyzed", "active", "confirmed"].includes(status)) return "ok";
  if (["failed", "rejected", "needs_reconnect", "expired", "blocked", "revoked", "disconnected", "unsupported"].includes(status)) return "rose";
  if (["needs_review", "missing_permissions", "unverified", "partial", "processing", "rate_limited", "unknown", "draft", "creative_ready", "scheduled", "publishing"].includes(status)) return "gold";
  if (["fixture", "planned", "extracted"].includes(status)) return "blue";
  return "neutral";
}

export function rangeQuery(range: RangeKey, start: string, end: string, accountId: string): string {
  const params = new URLSearchParams({ range });
  if (range === "custom") {
    params.set("start", start);
    params.set("end", end);
  }
  if (accountId) params.set("account_id", accountId);
  return params.toString();
}

export function utcDays(start: string, end: string): string {
  const first = new Date(start);
  const last = new Date(new Date(end).getTime() - 86_400_000);
  const day = (value: Date) => value.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  return last.getTime() <= first.getTime() ? `${day(first)} (UTC day)` : `${day(first)} to ${day(last)} (UTC days)`;
}

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
