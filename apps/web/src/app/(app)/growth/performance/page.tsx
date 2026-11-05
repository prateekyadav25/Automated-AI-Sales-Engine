"use client";

import { Notice, Panel, Stats } from "@/components/ds";
import { AccountTags, Cell, GrowthNav, GrowthTable, ProvenanceTag, StatusTag } from "@/components/growth-ui";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Field, Input, Select } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { when } from "@/lib/format";
import {
  RANGES,
  coverageText,
  growth,
  metricText,
  rangeQuery,
  utcDays,
  type AttributionView,
  type GrowthAccount,
  type PerformanceView,
  type Publication,
  type RangeKey,
} from "@/lib/growth";
import { ApiError } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

const RANGE_LABELS: Record<RangeKey, string> = { "1d": "Last day", "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days", custom: "Custom" };

function failure(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function amounts(values: Record<string, string>): string {
  const entries = Object.entries(values);
  return entries.length ? entries.map(([currency, amount]) => `${currency} ${Number(amount).toLocaleString()}`).join(" · ") : "None recorded";
}

export default function GrowthPerformancePage() {
  const { can } = useAuth();
  const [range, setRange] = useState<RangeKey>("7d");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [accountId, setAccountId] = useState("");
  const enabled = can("social_growth.read") && (range !== "custom" || Boolean(start && end));
  const query = rangeQuery(range, start, end, accountId);
  const accounts = useQuery({ queryKey: ["growth-accounts"], queryFn: () => growth<GrowthAccount[]>("/accounts"), enabled: can("social_growth.read") });
  const performance = useQuery({ queryKey: ["growth-performance", query], queryFn: () => growth<PerformanceView>(`/performance?${query}`), enabled });
  const attribution = useQuery({ queryKey: ["growth-attribution", query], queryFn: () => growth<AttributionView>(`/attribution?${query}`), enabled });
  const publications = useQuery({ queryKey: ["growth-publications"], queryFn: () => growth<Publication[]>("/publications"), enabled: can("social_growth.read") });
  if (!can("social_growth.read")) return <DeniedState />;
  return (
    <div>
      <PageHeader
        eyebrow="Social growth"
        title="Organic performance, traffic, and leads"
        subtitle="Provider readings with their retrieval time and evidence label, then traffic, enquiries, qualified leads, and sales as separate measurements. A missing reading is shown as unavailable, never as zero."
      />
      <GrowthNav />
      <div className="mb-6 flex flex-wrap items-end gap-3">
        <Field label="Period">
          <Select value={range} onChange={(event) => setRange(event.target.value as RangeKey)} aria-label="Period">
            {RANGES.map((key) => (
              <option key={key} value={key}>
                {RANGE_LABELS[key]}
              </option>
            ))}
          </Select>
        </Field>
        {range === "custom" ? (
          <>
            <Field label="From">
              <Input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
            </Field>
            <Field label="To">
              <Input type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
            </Field>
          </>
        ) : null}
        <Field label="Account">
          <Select value={accountId} onChange={(event) => setAccountId(event.target.value)}>
            <option value="">All accounts</option>
            {(accounts.data ?? []).map((account) => (
              <option key={account.id} value={account.id}>
                {account.platform} · {account.name || account.external_id}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {range === "custom" && !(start && end) ? <Notice title="Choose both dates" body="A custom period needs a start and an end date." /> : null}
      {performance.isLoading || attribution.isLoading ? <LoadingState label="Reading stored provider readings" /> : null}
      {performance.isError ? <ErrorState message={failure(performance.error, "Performance could not be loaded.")} /> : null}
      {attribution.data ? (
        <div className="mb-6">
          <Stats
            items={[
              { name: "Tracked link clicks", value: String(attribution.data.traffic.first_party_clicks), note: `${attribution.data.traffic.bot_clicks_excluded} automated visits excluded` },
              { name: "Website sessions (GA4)", value: attribution.data.traffic.ga4.status === "recorded" ? metricText(attribution.data.traffic.ga4.rows.reduce((sum, row) => sum + (row.sessions ?? 0), 0)) : "Unavailable", note: attribution.data.traffic.ga4.status === "recorded" ? `${attribution.data.traffic.ga4.coverage_days} of ${attribution.data.traffic.ga4.range_days} days` : attribution.data.traffic.ga4.detail },
              { name: "Enquiries", value: String(attribution.data.enquiries.count), note: `${attribution.data.enquiries.leads} lead(s)` },
              { name: "Qualified leads", value: String(attribution.data.qualified_leads.count), note: "Stored sales-qualified assessments" },
              { name: "Won purchases", value: String(attribution.data.sales.won_purchases), note: amounts(attribution.data.sales.amounts) },
              { name: "Fixture sales", value: amounts(attribution.data.sales.fixture_amounts), note: "Kept out of real totals" },
            ]}
          />
          <p className="mt-2 text-xs text-[var(--muted)]">{attribution.data.traffic.definition} {attribution.data.enquiries.definition} {attribution.data.sales.definition}</p>
        </div>
      ) : null}
      {performance.data ? (
        <div className="space-y-6">
          <p className="text-xs text-[var(--muted)]">
            Period {utcDays(performance.data.range.start, performance.data.range.end)}. {performance.data.note}
          </p>
          {performance.data.accounts.length === 0 ? (
            <EmptyState title="No accounts" body="Connect an account to read its insights." />
          ) : (
            performance.data.accounts.map((section) => (
              <Panel
                key={section.account.id}
                title={`${section.account.platform === "instagram" ? "Instagram" : "Facebook"} · ${section.account.name}`}
                extra={<AccountTags provenance={section.evidence} status={section.account.status} />}
              >
                {section.evidence === "fixture" ? <Notice title="Fixture evidence" body="This is a fixture account. Any reading shown here came from a scripted test provider, is not a live Meta result, and is never added to live totals." /> : null}
                {section.account_metrics.metrics.length === 0 ? (
                  <p className="text-sm text-[var(--muted)]">No account reading is stored for this period. Values are unavailable, not zero.</p>
                ) : (
                  <GrowthTable head={["Metric", "Value", "How it is combined", "Coverage", "Read"]}>
                    {section.account_metrics.metrics.map((row) => (
                      <tr key={row.metric}>
                        <Cell>{row.metric.replaceAll("_", " ")}</Cell>
                        <Cell className="num">{metricText(row.value, 1)}</Cell>
                        <Cell className="text-xs text-[var(--muted)]">{row.aggregation}</Cell>
                        <Cell className="text-xs">{coverageText(row)}</Cell>
                        <Cell className="text-xs text-[var(--muted)]">{row.retrieved_at ? when(row.retrieved_at) : row.error || "—"}</Cell>
                      </tr>
                    ))}
                  </GrowthTable>
                )}
                <div className="mt-4">
                  <p className="mb-2 text-sm font-medium text-navy">
                    Posts in this period ({section.media.posts.length}
                    {section.media.unmeasured_posts ? `, ${section.media.unmeasured_posts} without readings` : ""})
                  </p>
                  {section.media.posts.length === 0 ? (
                    <p className="text-sm text-[var(--muted)]">No post from this account falls in the period.</p>
                  ) : (
                    <GrowthTable head={["Posted", "Post", "Origin", "Readings"]}>
                      {section.media.posts.map((post) => (
                        <tr key={post.id}>
                          <Cell className="whitespace-nowrap text-xs">{when(post.posted_at)}</Cell>
                          <Cell className="max-w-sm text-xs">
                            {post.caption}
                            {post.permalink ? (
                              <a className="ml-1 text-brand" href={post.permalink} target="_blank" rel="noreferrer">
                                View
                              </a>
                            ) : null}
                          </Cell>
                          <Cell className="text-xs">
                            {post.origin} · {post.format || "—"}
                          </Cell>
                          <Cell className="text-xs">
                            {post.measured
                              ? Object.entries(post.metrics)
                                  .map(([metric, value]) => `${metric.replaceAll("_", " ")} ${metricText(value)}`)
                                  .join(" · ")
                              : "Unavailable: not read yet"}
                          </Cell>
                        </tr>
                      ))}
                    </GrowthTable>
                  )}
                </div>
              </Panel>
            ))
          )}
          {attribution.data?.traffic.ga4.status === "recorded" ? (
            <Panel title="Website sessions from social sources (GA4)">
              <GrowthTable head={["Source", "Medium", "Campaign", "Sessions", "Users (daily sum)", "Key events"]}>
                {attribution.data.traffic.ga4.rows.map((row) => (
                  <tr key={`${row.source}-${row.medium}-${row.campaign}`}>
                    <Cell>{row.source}</Cell>
                    <Cell>{row.medium}</Cell>
                    <Cell>{row.campaign}</Cell>
                    <Cell className="num">{metricText(row.sessions)}</Cell>
                    <Cell className="num">{metricText(row.total_users_daily_sum)}</Cell>
                    <Cell className="num">{metricText(row.key_events)}</Cell>
                  </tr>
                ))}
              </GrowthTable>
              <p className="mt-2 text-xs text-[var(--muted)]">{attribution.data.traffic.ga4.note}</p>
            </Panel>
          ) : null}
          <Panel title="Publications">
            {publications.isError ? <ErrorState message="Publications could not be loaded." /> : null}
            {(publications.data ?? []).length === 0 ? (
              <p className="text-sm text-[var(--muted)]">Nothing has been sent to Meta from this workspace.</p>
            ) : (
              <GrowthTable head={["Platform", "Format", "Status", "Provider id", "Attempts", "Evidence"]}>
                {(publications.data ?? []).map((row) => (
                  <tr key={row.id}>
                    <Cell>{row.platform}</Cell>
                    <Cell>{row.format}</Cell>
                    <Cell>
                      <StatusTag status={row.status} /> <span className="text-xs text-[var(--muted)]">{row.last_error}</span>
                    </Cell>
                    <Cell className="text-xs">
                      {row.permalink ? (
                        <a className="text-brand" href={row.permalink} target="_blank" rel="noreferrer">
                          {row.external_id}
                        </a>
                      ) : (
                        row.external_id || "—"
                      )}
                    </Cell>
                    <Cell className="num">{row.attempts}</Cell>
                    <Cell>
                      <ProvenanceTag value={row.provenance} /> <span className="text-xs text-[var(--muted)]">{row.api_version}</span>
                    </Cell>
                  </tr>
                ))}
              </GrowthTable>
            )}
          </Panel>
        </div>
      ) : null}
    </div>
  );
}
