"use client";

import { Line, Notice, Panel, Stats } from "@/components/ds";
import { AccountTags, GrowthNav, ModeNotice, StatusTag } from "@/components/growth-ui";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { when } from "@/lib/format";
import { growth, type Overview, type Recommendation } from "@/lib/growth";
import { ApiError } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

export default function GrowthCommandCenter() {
  const { can } = useAuth();
  const client = useQueryClient();
  const overview = useQuery({
    queryKey: ["growth-overview"],
    queryFn: () => growth<Overview>("/overview"),
    enabled: can("social_growth.read"),
    refetchInterval: 15000,
  });
  const generate = useMutation({
    mutationFn: () => growth<Recommendation[]>("/recommendations/generate", { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["growth-overview"] }),
  });
  if (!can("social_growth.read")) return <DeniedState />;
  if (overview.isLoading) return <LoadingState label="Reading the social growth workspace" />;
  if (overview.isError || !overview.data) return <ErrorState message={overview.error instanceof ApiError ? overview.error.message : "The command centre could not be loaded."} />;
  const data = overview.data;
  const caps = data.automation.capabilities;
  const facts = data.brand.facts;
  const live = data.accounts.filter((row) => row.provenance === "live" && !["disconnected", "revoked"].includes(row.status));
  const fixtures = data.accounts.filter((row) => row.provenance === "fixture" && row.status !== "disconnected");
  const pipeline = data.calendar.next_30_days_by_status;
  return (
    <div>
      <PageHeader
        eyebrow="Social growth"
        title="Social Growth Command Center"
        subtitle="Brand facts, accounts, the rolling calendar, creative review, organic performance, traffic, and leads for Facebook and Instagram. Every number is a stored provider reading or a stored count."
      />
      <GrowthNav />
      <ModeNotice publishMode={caps.publish_mode} insightsMode={caps.insights_mode} />
      {!data.flag_enabled ? (
        <Notice title="Automation is off for this workspace" body="ENABLE_SOCIAL_GROWTH is off, so nothing plans, renders, or publishes by itself. Manual planning and review still work. Turn it on in Feature controls when the strategy is approved." />
      ) : null}
      {data.demo_scope ? <Notice kind="warn" title={`Demonstration scope is ${data.demo_scope.status}`} body="A DEMO workspace cannot read Meta or publish while this scope is in place. Growth posts are outside the demonstration." /> : null}
      <Stats
        items={[
          { name: "Live accounts", value: String(live.length), note: fixtures.length ? `${fixtures.length} fixture account(s) not counted` : "Facebook Pages and Instagram" },
          { name: "Approved facts", value: String(facts.approved ?? 0), note: `${data.brand.claims_waiting} claim(s) waiting for review` },
          { name: "Planned in 7 days", value: String(data.calendar.next_7_days), note: data.strategy ? `Strategy version ${data.strategy.version}` : "No approved strategy" },
          { name: "Waiting for review", value: String(data.review_queue), note: "Creative drafts and flagged posts" },
          { name: "Live posts published", value: String(data.live_publication_count), note: "Provider ids stored" },
          { name: "Enquiries (30 days)", value: String(data.attribution_30d.enquiries), note: `${data.attribution_30d.qualified_leads} qualified · ${data.attribution_30d.won_purchases} won` },
        ]}
      />
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel title="Brand overview" extra={<Link className="btn" href="/growth/brand">Open</Link>}>
          {data.brand.status === "not_started" && Object.keys(facts).length === 0 ? (
            <EmptyState title="No brand analysis yet" body="Read the company website first. Facts keep their page and time, and claims wait for review." action={<Link className="btn primary" href="/growth/brand">Analyze the website</Link>} />
          ) : (
            <div>
              <Line label="Company" value={data.brand.company_name || "Not found on the site"} />
              <Line label="Website" value={data.brand.website_url || "—"} />
              <Line label="Website analysis" value={<StatusTag status={data.brand.status} />} />
              <Line label="Last read" value={when(data.brand.last_analysis_at)} />
              <Line label="Facts" value={Object.entries(facts).map(([state, count]) => `${count} ${state.replaceAll("_", " ")}`).join(" · ") || "None"} />
            </div>
          )}
        </Panel>
        <Panel title="Connected accounts" extra={<Link className="btn" href="/growth/accounts">Manage</Link>}>
          {data.accounts.length === 0 ? (
            <EmptyState title="No accounts" body="Connect a Facebook Page or an Instagram professional account. Each one keeps its own encrypted token." />
          ) : (
            <ul className="space-y-2 text-sm">
              {data.accounts.map((account) => (
                <li key={account.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    {account.platform === "instagram" ? "Instagram" : "Facebook"} · {account.name || account.username || account.external_id}
                  </span>
                  <AccountTags provenance={account.provenance} status={account.status} />
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="Content calendar" extra={<Link className="btn" href="/growth/calendar">Open</Link>}>
          {Object.keys(pipeline).length === 0 ? (
            <p className="text-sm text-[var(--muted)]">Nothing is planned for the next 30 days. Approve a strategy and plan the calendar.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {Object.entries(pipeline).map(([status, count]) => (
                <span key={status} className="flex items-center gap-1 text-sm">
                  <StatusTag status={status} /> {count}
                </span>
              ))}
            </div>
          )}
        </Panel>
        <Panel title="Creative studio" extra={<Link className="btn" href="/growth/studio">Review</Link>}>
          <Line label="Waiting for review" value={String(data.review_queue)} />
          <Line label="Image and carousel rendering" value={caps.image_rendering.ready ? "Ready" : caps.image_rendering.detail} />
          <Line label="Reels (FFmpeg)" value={caps.video_rendering.ready ? "Ready" : caps.video_rendering.detail} />
          <Line label="Model imagery" value={caps.model_imagery.detail} />
        </Panel>
        <Panel title="Organic performance, traffic, and leads" extra={<Link className="btn" href="/growth/performance">Open</Link>}>
          <Line label="Tracked link clicks (30 days)" value={String(data.attribution_30d.first_party_clicks)} />
          <Line label="Website sessions (GA4)" value={data.attribution_30d.ga4_status === "recorded" ? "Recorded" : "Unavailable: GA4 is not connected"} />
          <Line label="Attributed enquiries" value={String(data.attribution_30d.enquiries)} />
          <Line label="Qualified leads" value={String(data.attribution_30d.qualified_leads)} />
          <Line label="Won purchases" value={String(data.attribution_30d.won_purchases)} />
        </Panel>
        <Panel title="Automation health">
          <Line label="Graph API version" value={caps.graph_api_version} />
          <Line label="Publishing" value={caps.publish_mode} />
          <Line label="Insight reads" value={caps.insights_mode} />
          <Line label="GA4 reads" value={caps.ga4_mode} />
          <Line label="Public media address" value={caps.public_media_ready ? caps.public_media_base : `${caps.public_media_base} (not public; Instagram cannot fetch it)`} />
          <Line label="Execution grants" value={data.automation.grants.filter((grant) => grant.status === "active").map((grant) => `${grant.platform} ≤${grant.volume_cap}/day`).join(", ") || "None. Every post needs an inbox approval."} />
          {data.automation.blocked.length ? (
            <div className="mt-3">
              <p className="text-sm font-medium text-navy">Waiting or blocked</p>
              <ul className="mt-1 space-y-1 text-xs text-[var(--muted)]">
                {data.automation.blocked.map((row) => (
                  <li key={row.id}>
                    {when(row.planned_for)} · {row.status.replaceAll("_", " ")} · {row.blocker}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {data.automation.runs.length ? (
            <div className="mt-3">
              <p className="text-sm font-medium text-navy">Recent automation runs</p>
              <ul className="mt-1 space-y-1 text-xs text-[var(--muted)]">
                {data.automation.runs.slice(0, 5).map((run) => (
                  <li key={run.id}>
                    {when(run.created_at)} · {run.kind.replace("growth:", "")} · {run.summary}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Panel>
      </div>
      <div className="mt-6">
        <Panel
          title="Recommendations"
          extra={
            can("social_growth.write") ? (
              <Button type="button" variant="ghost" disabled={generate.isPending} onClick={() => generate.mutate()}>
                {generate.isPending ? "Reading evidence…" : "Refresh from evidence"}
              </Button>
            ) : null
          }
        >
          {generate.isError ? <ErrorState message={generate.error instanceof ApiError ? generate.error.message : "Recommendations could not be prepared."} /> : null}
          {data.recommendations.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No recommendation is open. Recommendations need measured live posts and never change the strategy by themselves.</p>
          ) : (
            <ul className="space-y-3">
              {data.recommendations.map((item) => (
                <li key={item.id} className="rounded-md border border-[var(--line)] p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusTag status={item.verdict} />
                    <span className="text-xs uppercase tracking-[0.14em] text-[var(--muted)]">{item.kind}</span>
                    <span className="text-xs text-[var(--muted)]">Sample {item.sample_size}</span>
                  </div>
                  <p className="mt-2 text-ink">{item.observation}</p>
                  <p className="mt-1 text-[var(--muted)]">{item.limitation}</p>
                  <p className="mt-1">{item.proposed_change}</p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
