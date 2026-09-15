"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import { subscribeAutonomyEvents } from "@/lib/sse";
import type { AutonomyActivity, AutonomyRun, AutonomyStatus, AutopilotSettings, LifecycleLane, ProviderAction } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

function DeadLetterPanel() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["provider-actions-dead", page],
    queryFn: async () =>
      api<ProviderAction[]>(`/api/v1/providers/actions?status=DEAD_LETTER&page=${page}&page_size=10`),
    enabled: can("autonomy.read"),
    refetchInterval: 5000,
  });
  const retry = useMutation({
    mutationFn: (id: string) => api(`/api/v1/providers/actions/${id}/retry`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["provider-actions-dead"] }),
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api(`/api/v1/providers/actions/${id}/cancel`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["provider-actions-dead"] }),
  });
  const rows = query.data?.data ?? [];
  const total = query.data?.meta?.total ?? rows.length;
  if (query.isLoading) return <p className="mt-4 text-xs text-[var(--muted)]">Reading dead letters</p>;
  if (rows.length === 0) {
    return <p className="mt-4 text-xs text-[var(--muted)]" data-testid="dead-letter-empty">No dead-letter provider work.</p>;
  }
  return (
    <div className="mt-4" data-testid="dead-letter-panel">
      <p className="text-xs font-semibold text-navy">Dead letters</p>
      <ul className="mt-2 space-y-2 text-xs">
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center justify-between gap-2" data-testid="dead-letter-row">
            <span>
              {row.action_type} · {row.provider} · {row.last_error || "failed"}
              <span className="mt-1 block text-[var(--muted)]">
                {row.attempts ?? 0} attempts · {row.entity_type || "entity"} {row.entity_id || ""}
                {" · "}
                {row.created_at ? new Date(row.created_at).toLocaleString() : "no timestamp"}
              </span>
            </span>
            {can("autonomy.write") ? (
              <span className="flex gap-2">
                <Button variant="line" onClick={() => retry.mutate(row.id)}>Retry</Button>
                <Button variant="ghost" onClick={() => cancel.mutate(row.id)}>Cancel</Button>
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {total > 10 ? (
        <div className="mt-2 flex gap-2">
          <Button variant="ghost" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page === 1}>
            Previous
          </Button>
          <Button variant="ghost" onClick={() => setPage((value) => value + 1)} disabled={page * 10 >= total}>
            Next
          </Button>
        </div>
      ) : null}
    </div>
  );
}

const TODAY_LABELS: { key: keyof AutonomyStatus["today"]; label: string }[] = [
  { key: "targets_discovered", label: "Targets discovered" },
  { key: "leads_enriched", label: "Leads enriched" },
  { key: "leads_scored", label: "Leads scored" },
  { key: "leads_qualified", label: "Leads qualified" },
  { key: "research_completed", label: "Research completed" },
  { key: "messages_prepared", label: "Messages prepared" },
  { key: "approvals_waiting", label: "Approvals waiting" },
  { key: "meetings_booked", label: "Meetings booked" },
  { key: "opportunities_created", label: "Opportunities created" },
  { key: "customers_at_risk", label: "Customers at risk" },
  { key: "renewals_processed", label: "Renewals processed" },
  { key: "expansion_opportunities", label: "Expansion opportunities" },
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
    queryFn: async () => (await api<AutonomyActivity[]>("/api/v1/autonomy/activity?page=1&page_size=40")).data ?? [],
    enabled: can("autonomy.read"),
    refetchInterval: 5000,
  });
  const runsQuery = useQuery({
    queryKey: ["autonomy-runs"],
    queryFn: async () => (await api<AutonomyRun[]>("/api/v1/autonomy/runs")).data ?? [],
    enabled: can("autonomy.read"),
    refetchInterval: 5000,
  });
  const lanesQuery = useQuery({
    queryKey: ["post-sale-lanes"],
    queryFn: async () => (await api<LifecycleLane[]>("/api/v1/post-sale/lanes")).data ?? [],
    enabled: can("autonomy.read"),
    refetchInterval: 5000,
  });
  const connectorsQuery = useQuery({
    queryKey: ["integration-connectors"],
    queryFn: async () =>
      (
        await api<{ provider: string; name: string; connected_customers: number; stale_customers: number; failed_syncs: number }[]>(
          "/api/v1/integrations/connectors",
        )
      ).data ?? [],
    enabled: can("integrations.read"),
    refetchInterval: 5000,
  });
  const toggle = useMutation({
    mutationFn: (patch: Partial<AutopilotSettings>) =>
      api<AutopilotSettings>("/api/v1/autonomy/settings", {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["autonomy-settings"] });
      void client.invalidateQueries({ queryKey: ["autonomy-status"] });
    },
  });
  useEffect(() => subscribeAutonomyEvents(() => {
    void client.invalidateQueries({ queryKey: ["autonomy-status"] });
    void client.invalidateQueries({ queryKey: ["autonomy-activity"] });
    void client.invalidateQueries({ queryKey: ["autonomy-runs"] });
    void client.invalidateQueries({ queryKey: ["provider-actions-dead"] });
  }), [client]);
  const pauseTenant = useMutation({
    mutationFn: () => api("/api/v1/autonomy/pause", { method: "POST", body: JSON.stringify({ scope: "tenant" }) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["autonomy-settings"] });
      void client.invalidateQueries({ queryKey: ["autonomy-status"] });
    },
  });
  const resumeTenant = useMutation({
    mutationFn: () => api("/api/v1/autonomy/resume", { method: "POST", body: JSON.stringify({ scope: "tenant" }) }),
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
              <Button variant="line" onClick={() => toggle.mutate({ enabled: !settings.enabled })} disabled={toggle.isPending}>
                {settings.enabled ? "Disable Autopilot" : "Enable Autopilot"}
              </Button>
            ) : null}
            {can("autonomy.write") && settings ? (
              <Button
                variant="line"
                data-testid="emergency-stop"
                onClick={() => toggle.mutate({ emergency_stop: !settings.emergency_stop })}
                disabled={toggle.isPending}
              >
                {settings.emergency_stop ? "Clear emergency stop" : "Emergency stop"}
              </Button>
            ) : null}
            {can("autonomy.write") ? (
              <Button data-testid="pause-tenant" variant="ghost" onClick={() => pauseTenant.mutate()} disabled={pauseTenant.isPending}>
                Pause tenant
              </Button>
            ) : null}
            {can("autonomy.write") ? (
              <Button data-testid="resume-tenant" variant="ghost" onClick={() => resumeTenant.mutate()} disabled={resumeTenant.isPending}>
                Resume tenant
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
              {settings?.emergency_stop ? (
                <p className="mt-2 text-xs text-[#e08b7a]" data-testid="emergency-stop-active">Emergency stop is active. New external actions are suspended.</p>
              ) : null}
              {status.scheduler_unhealthy ? (
                <p className="mt-2 text-xs text-[#e08b7a]" data-testid="scheduler-unhealthy">Scheduler is unhealthy. Beat heartbeat is stale or missing.</p>
              ) : null}
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
          {lanesQuery.data?.length ? (
            <section className="mb-6">
              <p className="mb-3 text-sm font-semibold text-navy">Lifecycle lanes</p>
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                {lanesQuery.data.map((lane) => (
                  <article key={lane.lane} className="panel p-4" data-testid={`lane-${lane.lane.toLowerCase()}`}>
                    <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">{lane.lane}</p>
                    <p className="mt-2 text-xl font-semibold text-navy">{lane.running}</p>
                    <p className="mt-1 text-xs text-[var(--muted)]">
                      {lane.waiting} waiting · {lane.blocked} blocked · {lane.completed_today} today
                    </p>
                  </article>
                ))}
              </div>
            </section>
          ) : null}
          <section className="mb-6 grid gap-4 xl:grid-cols-2">
            <div className="panel p-5">
              <p className="text-sm font-semibold text-navy">Provider health</p>
              <p className="mt-1 text-xs text-[var(--muted)]" data-testid="provider-ops-summary">
                {status.pending_actions ?? 0} pending · {status.dead_letters ?? 0} dead letters
                {status.alerts?.length ? ` · alerts: ${status.alerts.join(", ")}` : ""}
              </p>
              <ul className="mt-4 space-y-3 text-sm">
                {status.providers.map((row) => (
                  <li key={row.name} className="flex items-start justify-between gap-3" data-testid={`provider-${row.name.toLowerCase().replaceAll(" ", "-")}`}>
                    <span>
                      {row.name}
                      <span className="mt-1 block text-xs text-[var(--muted)]">
                        Last success {row.last_success_at ? new Date(row.last_success_at).toLocaleString() : "never"}
                        {row.last_error_summary ? ` · ${row.last_error_summary}` : ""}
                      </span>
                    </span>
                    <span className="text-right">
                      <Badge
                        tone={row.mode === "LIVE" || row.state === "CONNECTED" ? "ok" : row.mode === "MOCK" || row.state === "MOCK" ? "gold" : "rose"}
                      >
                        {row.mode || row.state}
                      </Badge>
                      <span className="mt-1 block text-xs text-[var(--muted)]">
                        {row.state} · {row.pending_actions ?? 0} pending · {row.failed_actions ?? 0} failed
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
              {connectorsQuery.data?.length ? (
                <ul className="mt-4 space-y-2 text-xs text-[var(--muted)]" data-testid="signal-connector-counts">
                  {connectorsQuery.data.map((row) => (
                    <li key={row.provider}>
                      {row.name}: {row.connected_customers} connected · {row.stale_customers} stale · {row.failed_syncs} failed
                    </li>
                  ))}
                </ul>
              ) : null}
              {status.blocked_config.length ? (
                <p className="mt-4 text-sm text-[var(--muted)]" data-testid="blocked-config">
                  Blocked by configuration: {status.blocked_config.join(", ")}.{" "}
                  <Link href="/admin/integrations" className="text-brand">Connect integrations</Link>
                </p>
              ) : null}
              {can("autonomy.write") && settings ? (
                <div className="mt-4 flex flex-wrap gap-2" data-testid="channel-pauses">
                  <Button variant="ghost" onClick={() => toggle.mutate({ email_channel_paused: !settings.email_channel_paused })}>
                    {settings.email_channel_paused ? "Resume email" : "Pause email"}
                  </Button>
                  <Button variant="ghost" onClick={() => toggle.mutate({ ads_channel_paused: !settings.ads_channel_paused })}>
                    {settings.ads_channel_paused ? "Resume ads" : "Pause ads"}
                  </Button>
                  <Button variant="ghost" onClick={() => toggle.mutate({ voice_channel_paused: !settings.voice_channel_paused })}>
                    {settings.voice_channel_paused ? "Resume voice" : "Pause voice"}
                  </Button>
                  <Button variant="ghost" onClick={() => toggle.mutate({ discovery_channel_paused: !settings.discovery_channel_paused })}>
                    {settings.discovery_channel_paused ? "Resume discovery" : "Pause discovery"}
                  </Button>
                </div>
              ) : null}
              <DeadLetterPanel />
            </div>
            <div className="panel p-5">
              <p className="text-sm font-semibold text-navy">Activity</p>
              {activity.length === 0 ? (
                <p className="mt-4 text-sm text-[var(--muted)]">No persisted automation events yet.</p>
              ) : (
                <ol className="mt-4 space-y-3 text-sm">
                  {activity.slice(0, 40).map((row) => (
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
