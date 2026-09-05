"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import type { AutonomyActivity, AutonomyRun, AutonomyStatus, AutopilotSettings } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

const TODAY_LABELS: { key: keyof AutonomyStatus["today"]; label: string }[] = [
  { key: "targets_discovered", label: "Targets discovered" },
  { key: "leads_enriched", label: "Leads enriched" },
  { key: "leads_scored", label: "Leads scored" },
  { key: "leads_qualified", label: "Leads qualified" },
  { key: "research_completed", label: "Research completed" },
  { key: "messages_prepared", label: "Messages prepared" },
  { key: "approvals_waiting", label: "Approvals waiting" },
  { key: "opportunities_created", label: "Opportunities created" },
];

export default function AutopilotRunsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const statusQuery = useQuery({
    queryKey: ["autonomy-status"],
    queryFn: async () => (await api<AutonomyStatus>("/api/v1/autonomy/status")).data,
    enabled: can("autonomy.read"),
    refetchInterval: 5000,
  });
  const settingsQuery = useQuery({
    queryKey: ["autonomy-settings"],
    queryFn: async () => (await api<AutopilotSettings>("/api/v1/autonomy/settings")).data,
    enabled: can("autonomy.read"),
  });
  const activityQuery = useQuery({
    queryKey: ["autonomy-activity"],
    queryFn: async () => (await api<AutonomyActivity[]>("/api/v1/autonomy/activity")).data ?? [],
    enabled: can("autonomy.read"),
    refetchInterval: 5000,
  });
  const runsQuery = useQuery({
    queryKey: ["autonomy-runs"],
    queryFn: async () => (await api<AutonomyRun[]>("/api/v1/autonomy/runs")).data ?? [],
    enabled: can("autonomy.read"),
    refetchInterval: 5000,
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      api<AutopilotSettings>("/api/v1/autonomy/settings", {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["autonomy-settings"] });
      void client.invalidateQueries({ queryKey: ["autonomy-status"] });
    },
  });
  const start = useMutation({
    mutationFn: () => api<AutonomyRun>("/api/v1/autonomy/runs", { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["autonomy-runs"] });
      void client.invalidateQueries({ queryKey: ["autonomy-status"] });
      void client.invalidateQueries({ queryKey: ["autonomy-activity"] });
      void client.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  if (!can("autonomy.read")) return <DeniedState />;
  if (statusQuery.isLoading || runsQuery.isLoading) return <LoadingState label="Reading Autopilot" />;
  if (statusQuery.isError || runsQuery.isError) return <ErrorState message="Autopilot could not be assembled." />;
  const status = statusQuery.data;
  const settings = settingsQuery.data;
  const rows = runsQuery.data ?? [];
  const activity = activityQuery.data ?? [];
  const active = rows.filter((row) => ["running", "WAITING_FOR_APPROVAL"].includes(row.status));

  return (
    <div>
      <PageHeader
        eyebrow="Operations"
        title="Autopilot"
        subtitle="Continuous mode. Run now is only for acceleration. Approvals stay the human gate."
        actions={
          <div className="flex flex-wrap gap-2">
            {can("autonomy.write") && settings ? (
              <Button variant="line" onClick={() => toggle.mutate(!settings.enabled)} disabled={toggle.isPending}>
                {settings.enabled ? "Disable Autopilot" : "Enable Autopilot"}
              </Button>
            ) : null}
            {can("autonomy.write") ? (
              <Button onClick={() => start.mutate()} disabled={start.isPending}>
                {start.isPending ? "Running…" : "Run now"}
              </Button>
            ) : null}
          </div>
        }
      />
      {status ? (
        <>
          <section className="mb-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <article className="panel p-5" data-testid="autopilot-state">
              <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">System status</p>
              <p className="mt-2 text-2xl font-semibold text-navy">{status.enabled ? "ON" : "OFF"}</p>
              <p className="mt-2 text-xs text-[var(--muted)]">{status.worker}</p>
              <p className="mt-1 text-xs text-[var(--muted)]">
                Next cycle {status.next_cycle_at ? new Date(status.next_cycle_at).toLocaleString() : "when Beat or Run now fires"}
              </p>
            </article>
            <article className="panel p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Blocked by human</p>
              <p className="mt-2 text-2xl font-semibold text-navy">{status.blocked_human}</p>
              <Link href="/automation/approvals" className="mt-3 inline-block text-sm text-brand">Approvals</Link>
            </article>
            <article className="panel p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Blocked by policy</p>
              <p className="mt-2 text-2xl font-semibold text-navy">{status.blocked_policy}</p>
            </article>
            <article className="panel p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Errors</p>
              <p className="mt-2 text-2xl font-semibold text-navy">{status.failed_steps}</p>
            </article>
          </section>
          <section className="mb-6">
            <p className="mb-3 text-sm font-semibold text-navy">Today</p>
            <div className="grid gap-3 md:grid-cols-4">
              {TODAY_LABELS.map((item) => (
                <div key={item.key} className="panel p-4">
                  <p className="text-xs text-[var(--muted)]">{item.label}</p>
                  <p className="mt-1 text-xl font-semibold text-navy">{status.today[item.key]}</p>
                </div>
              ))}
            </div>
          </section>
          <section className="mb-6 grid gap-4 xl:grid-cols-2">
            <div className="panel p-5">
              <p className="text-sm font-semibold text-navy">Provider health</p>
              <ul className="mt-4 space-y-2 text-sm">
                {status.providers.map((row) => (
                  <li key={row.name} className="flex items-start justify-between gap-3">
                    <span>{row.name}</span>
                    <span className="text-right">
                      <Badge tone={row.state === "Connected" ? "ok" : row.state === "Mock" ? "gold" : "rose"}>{row.state}</Badge>
                      <span className="mt-1 block text-xs text-[var(--muted)]">{row.reason}</span>
                    </span>
                  </li>
                ))}
              </ul>
              {status.blocked_config.length ? (
                <p className="mt-4 text-sm text-[var(--muted)]">Blocked by configuration: {status.blocked_config.join(", ")}</p>
              ) : null}
            </div>
            <div className="panel p-5">
              <p className="text-sm font-semibold text-navy">Activity</p>
              {activity.length === 0 ? (
                <p className="mt-4 text-sm text-[var(--muted)]">No persisted automation events yet.</p>
              ) : (
                <ol className="mt-4 space-y-3 text-sm">
                  {activity.slice(0, 12).map((row) => (
                    <li key={`${row.kind}-${row.id}`}>
                      <p className="font-medium">{row.title}</p>
                      <p className="text-xs text-[var(--muted)]">
                        {new Date(row.occurred_at).toLocaleString()} · {row.entity_type}
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </section>
        </>
      ) : null}
      <p className="mb-3 text-sm font-semibold text-navy">Active and recent work</p>
      {start.isError ? <p className="mb-4 text-sm text-[#e08b7a]">The run could not be stored.</p> : null}
      {rows.length === 0 ? (
        <EmptyState title="No runs yet" body="Enable Autopilot or use Run now. Empty stays empty until a run is persisted." />
      ) : (
        <div className="space-y-4">
          {active.length ? <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">{active.length} active</p> : null}
          {rows.map((row) => (
            <article key={row.id} className="panel p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-navy">{row.summary || "Run stored."}</p>
                  <p className="mt-1 text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
                    {labelize(row.trigger)} · {row.workflow || "cycle"} · {row.finished_at ? new Date(row.finished_at).toLocaleString() : "in progress"}
                  </p>
                </div>
                <Badge tone={row.status === "completed" ? "ok" : "gold"}>{labelize(row.status)}</Badge>
              </div>
              <ol className="mt-4 space-y-2 text-sm">
                {row.steps.map((step) => (
                  <li key={step.id} className="flex flex-wrap justify-between gap-3">
                    <span>{labelize(step.name)}</span>
                    <Badge tone={step.status === "completed" ? "ok" : step.status === "FAILED" ? "rose" : "neutral"}>
                      {labelize(step.status)}
                    </Badge>
                  </li>
                ))}
              </ol>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
