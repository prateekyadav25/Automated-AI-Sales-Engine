"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

type PilotCheck = {
  key: string;
  state: string;
  detail: string;
  required: boolean;
};

type PilotReadiness = {
  operating_mode: string;
  environment: string;
  can_activate_pilot: boolean;
  can_activate_production: boolean;
  blockers: string[];
  items: PilotCheck[];
};

function tone(state: string): "ok" | "gold" | "rose" | "neutral" {
  if (state === "READY") return "ok";
  if (state === "MOCK" || state === "OPTIONAL" || state === "PARTIAL") return "gold";
  if (state === "BLOCKER") return "rose";
  return "neutral";
}

export default function PilotReadinessPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["pilot-readiness"],
    queryFn: async () => (await api<PilotReadiness>("/api/v1/pilot/readiness")).data,
    enabled: can("pilot.view"),
    refetchInterval: 5000,
  });
  const activate = useMutation({
    mutationFn: (target: string) =>
      api("/api/v1/pilot/activate", { method: "POST", body: JSON.stringify({ target, reason: "operator activate" }) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["pilot-readiness"] }),
  });
  const exported = useQuery({
    queryKey: ["pilot-config-export"],
    queryFn: async () => (await api<Record<string, unknown>>("/api/v1/pilot/config-export")).data,
    enabled: can("pilot.view"),
  });

  if (!can("pilot.view")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading pilot readiness" />;
  if (query.isError) return <ErrorState message="Pilot readiness could not be assembled." />;
  const data = query.data;
  if (!data) return <EmptyState title="No readiness" body="The API returned an empty checklist." />;

  return (
    <div>
      <PageHeader
        eyebrow="Admin"
        title="Pilot readiness"
        subtitle={`Tenant mode is ${data.operating_mode}. Deployment environment is ${data.environment}. Critical blockers refuse PILOT or PRODUCTION.`}
        actions={
          can("pilot.activate") ? (
            <div className="flex gap-2">
              <Button
                data-testid="activate-pilot"
                onClick={() => activate.mutate("PILOT")}
                disabled={activate.isPending || !data.can_activate_pilot}
              >
                Activate PILOT
              </Button>
              <Button
                variant="line"
                data-testid="activate-production"
                onClick={() => activate.mutate("PRODUCTION")}
                disabled={activate.isPending || !data.can_activate_production}
              >
                Activate PRODUCTION
              </Button>
            </div>
          ) : null
        }
      />
      <div className="mb-6 grid gap-3 md:grid-cols-3" data-testid="pilot-mode">
        <div className="panel p-5">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Operating mode</p>
          <p className="mt-2 text-2xl font-semibold text-navy">{data.operating_mode}</p>
        </div>
        <div className="panel p-5">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Environment</p>
          <p className="mt-2 text-2xl font-semibold text-navy">{data.environment}</p>
        </div>
        <div className="panel p-5">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Blockers</p>
          <p className="mt-2 text-2xl font-semibold text-navy">{data.blockers.length}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">{data.blockers.join(", ") || "None on required checks"}</p>
        </div>
      </div>
      {data.items.length === 0 ? (
        <EmptyState title="No checks" body="Readiness checks did not return items." />
      ) : (
        <ul className="space-y-3" data-testid="pilot-checklist">
          {data.items.map((item) => (
            <li key={item.key} className="panel p-4" data-testid={`pilot-check-${item.key}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-navy">{item.key}</p>
                  <p className="mt-1 text-xs text-[var(--muted)]">{item.detail}</p>
                </div>
                <Badge tone={tone(item.state)}>
                  {item.state}
                </Badge>
              </div>
            </li>
          ))}
        </ul>
      )}
      {activate.isError ? <p className="mt-4 text-sm text-[#e08b7a]">Activation was refused. Critical checks must pass.</p> : null}
      <h2 className="mb-3 mt-10 text-xl font-semibold text-navy">Config export</h2>
      <pre className="panel overflow-auto p-4 text-xs" data-testid="config-export">
        {exported.data ? JSON.stringify(exported.data, null, 2) : "Loading export…"}
      </pre>
    </div>
  );
}
