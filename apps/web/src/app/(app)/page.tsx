"use client";

import { GlassMotif, StageChips } from "@/components/glass-motif";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { money, pct } from "@/lib/format";
import type { AutonomyStatus, Overview, PostSaleAttention } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export default function CommandCenterPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["overview"],
    queryFn: async () => (await api<Overview>("/api/v1/command-center/overview")).data,
    enabled: can("command_center.read"),
  });
  const autonomy = useQuery({
    queryKey: ["autonomy-status"],
    queryFn: async () => (await api<AutonomyStatus>("/api/v1/autonomy/status")).data,
    enabled: can("autonomy.read"),
    refetchInterval: 5000,
  });
  const attention = useQuery({
    queryKey: ["post-sale-attention"],
    queryFn: async () => (await api<PostSaleAttention>("/api/v1/post-sale/attention")).data,
    enabled: can("success.read"),
    refetchInterval: 5000,
  });
  const roi = useQuery({
    queryKey: ["pilot-roi"],
    queryFn: async () =>
      (
        await api<{
          automation: { automated_internal_tasks: number; approval_actions: number; autonomous_execution_rate: number | null };
          pipeline: { ai_discovery_leads: number; all_leads: number };
        }>("/api/v1/pilot/roi")
      ).data,
    enabled: can("pilot.view"),
    refetchInterval: 5000,
  });

  if (!can("command_center.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Loading overview" />;
  if (query.isError) {
    return <ErrorState message="The command center could not be loaded." />;
  }
  const data = query.data;
  if (!data) return <EmptyState title="No data" body="The API returned an empty overview." />;

  const k = data.kpis;
  const empty = k.total_accounts === 0 && k.total_leads === 0 && k.open_opportunities === 0;
  const chart = data.pipeline_by_stage.map((row) => ({
    stage: row.stage.replaceAll("_", " "),
    amount: Number(row.amount),
  }));
  const status = autonomy.data;
  const nextHuman =
    status && status.today.approvals_waiting > 0
      ? `Review ${status.today.approvals_waiting} waiting approval${status.today.approvals_waiting === 1 ? "" : "s"}`
      : status && status.blocked_policy > 0
        ? "Clear consent or sequence blockers"
        : "Confirm ICP and leave Autopilot on";

  return (
    <div className="relative">
      <GlassMotif className="absolute -right-8 -top-10 w-[420px] opacity-40" />
      <div className="relative mb-6">
        <PageHeader
          className="mb-0"
          eyebrow="Start here"
          title="What the AI is doing for you"
          subtitle="Autopilot prepares the work. You approve send, spend, dial, and the last strategic meeting."
        />
        <StageChips />
      </div>
      {status ? (
        <div className="relative mb-8 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="panel p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">Autopilot</p>
            <p className="mt-2 text-2xl font-semibold text-navy">{status.enabled ? "ON" : "OFF"}</p>
            <p className="mt-1 text-xs text-[var(--muted)]">
              {status.last_cycle_at ? `Last cycle ${new Date(status.last_cycle_at).toLocaleString()}` : "No cycle stored yet"}
            </p>
            <Link href="/automation/runs" className="mt-4 inline-block text-sm text-brand">
              Open Autopilot
            </Link>
          </div>
          <div className="panel p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">Today</p>
            <p className="mt-2 text-2xl font-semibold text-navy">{status.today.leads_scored} scored</p>
            <p className="mt-1 text-xs text-[var(--muted)]">
              {status.today.leads_qualified} qualified · {status.today.research_completed} researched
            </p>
          </div>
          <div className="panel p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">Approvals required</p>
            <p className="mt-2 text-2xl font-semibold text-navy">{status.today.approvals_waiting}</p>
            <Link href="/automation/approvals" className="mt-4 inline-block text-sm text-brand">
              {status.today.approvals_waiting ? "Review Approvals" : "Open Approvals"}
            </Link>
          </div>
          <div className="panel p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">Next human action</p>
            <p className="mt-2 text-sm font-semibold text-navy">{nextHuman}</p>
            {status.blocked_config.length ? (
              <p className="mt-2 text-xs text-[var(--muted)]">Blocked by config: {status.blocked_config.join(", ")}</p>
            ) : (
              <p className="mt-2 text-xs text-[var(--muted)]">{status.blocked_policy} policy blocks</p>
            )}
          </div>
        </div>
      ) : (
        <ol className="relative mb-8 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {[
            { href: "/icps", title: "Who we sell to", label: "Open ICP" },
            { href: "/leads", title: "Leads", label: "Open leads" },
            { href: "/automation/runs", title: "Autopilot", label: "Open Autopilot" },
            { href: "/automation/approvals", title: "Approvals", label: "Open Approvals" },
          ].map((step) => (
            <li key={step.href} className="panel flex flex-col p-5">
              <h2 className="text-lg font-semibold text-navy">{step.title}</h2>
              <Link href={step.href} className="mt-4 inline-flex w-full items-center justify-center rounded-lg bg-brand px-3.5 py-2 text-[13px] font-semibold text-white">
                {step.label}
              </Link>
            </li>
          ))}
        </ol>
      )}
      {roi.data ? (
        <div className="relative mb-8 grid gap-3 md:grid-cols-3" data-testid="automation-roi">
          <div className="panel p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">Automated steps today</p>
            <p className="mt-2 text-2xl font-semibold text-navy">{roi.data.automation.automated_internal_tasks}</p>
          </div>
          <div className="panel p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">Autonomous execution rate</p>
            <p className="mt-2 text-2xl font-semibold text-navy">
              {roi.data.automation.autonomous_execution_rate == null
                ? "—"
                : `${Math.round(roi.data.automation.autonomous_execution_rate * 100)}%`}
            </p>
            <p className="mt-1 text-xs text-[var(--muted)]">System-executed / eligible. Not employee replacement.</p>
          </div>
          <div className="panel p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">AI-prepared pipeline</p>
            <p className="mt-2 text-2xl font-semibold text-navy">
              {roi.data.pipeline.ai_discovery_leads}/{roi.data.pipeline.all_leads || 0}
            </p>
            <p className="mt-1 text-xs text-[var(--muted)]">Revenue associated with AI-prepared opportunities uses provenance. Not AI generated revenue.</p>
          </div>
        </div>
      ) : null}
      {attention.data ? (
        <section className="relative mb-8">
          <p className="mb-3 text-sm font-semibold text-navy">Post-sale attention</p>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[
              { href: "/success", label: "Customers requiring attention", value: attention.data.customers_requiring_attention },
              { href: "/success", label: "Onboarding at risk", value: attention.data.onboarding_at_risk },
              { href: "/renewals", label: "Renewals approaching", value: attention.data.renewals_approaching },
              { href: "/renewals", label: "Renewals at risk", value: attention.data.renewals_at_risk },
              { href: "/expansion", label: "Expansion opportunities", value: attention.data.expansion_opportunities },
              { href: "/advocacy", label: "Advocacy candidates", value: attention.data.advocacy_candidates },
              ...(attention.data.usage_risk ? [{ href: "/success", label: "Usage risk", value: attention.data.usage_risk }] : []),
              ...(attention.data.support_risk ? [{ href: "/success", label: "Support risk", value: attention.data.support_risk }] : []),
              ...(attention.data.commercial_risk ? [{ href: "/success", label: "Commercial risk", value: attention.data.commercial_risk }] : []),
              ...(attention.data.high_utilization_candidates
                ? [{ href: "/expansion", label: "High utilization", value: attention.data.high_utilization_candidates }]
                : []),
            ].map((item) => (
              <Link key={item.label} href={item.href} className="panel p-5">
                <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">{item.label}</p>
                <p className="mt-2 text-2xl font-semibold text-navy">{item.value}</p>
              </Link>
            ))}
          </div>
        </section>
      ) : null}
      <p className="relative mb-4 text-sm font-semibold text-navy">Live totals from your tenant</p>
      {empty ? (
        <EmptyState title="Nothing in the pipeline yet" body="Create accounts, leads, and opportunities to start the flywheel." />
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {[
              ["Open pipeline", money(k.open_pipeline_value), "Unweighted"],
              ["Weighted", money(k.weighted_pipeline_value), "Probability applied"],
              ["Win rate", pct(k.win_rate), `${k.won_opportunities} won`],
              ["MQLs", String(k.mql_count), `${k.total_leads} leads`],
            ].map(([label, value, hint]) => (
              <div key={label} className="panel kpi-sheen p-5">
                <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">{label}</p>
                <p className="mt-2 text-3xl font-semibold tracking-tight text-navy">{value}</p>
                <p className="mt-1.5 text-xs text-[var(--muted)]">{hint}</p>
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="panel p-5 xl:col-span-2">
              <div className="mb-4 flex items-center justify-between">
                <p className="text-sm font-semibold text-navy">Pipeline mix</p>
                <Badge tone="blue">Deterministic</Badge>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chart}>
                    <XAxis dataKey="stage" tick={{ fill: "#64748B", fontSize: 11 }} />
                    <YAxis tick={{ fill: "#64748B", fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{
                        background: "rgba(255,255,255,0.9)",
                        border: "1px solid rgba(37,99,235,0.2)",
                        borderRadius: 12,
                        color: "#0F172A",
                        backdropFilter: "blur(12px)",
                      }}
                    />
                    <Bar dataKey="amount" radius={[6, 6, 0, 0]}>
                      {chart.map((row, index) => (
                        <Cell key={row.stage} fill={index === chart.length - 1 ? "#0F766E" : "#2563EB"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="panel p-5">
              <p className="text-sm font-semibold text-navy">Workspace pulse</p>
              <ul className="mt-4 space-y-3 text-sm">
                <li className="flex justify-between"><span className="text-[var(--muted)]">Accounts</span><span className="font-medium">{k.total_accounts}</span></li>
                <li className="flex justify-between"><span className="text-[var(--muted)]">Open opportunities</span><span className="font-medium">{k.open_opportunities}</span></li>
                <li className="flex justify-between"><span className="text-[var(--muted)]">Approvals</span><span className="font-medium">{k.pending_approvals}</span></li>
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
