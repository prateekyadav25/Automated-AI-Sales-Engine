"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { money, pct } from "@/lib/format";
import type { Forecast } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export default function ForecastPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["forecast"],
    queryFn: async () => (await api<Forecast[]>("/api/v1/lifecycle/forecast")).data ?? [],
    enabled: can("forecast.read"),
  });
  const refresh = useMutation({
    mutationFn: () => api("/api/v1/lifecycle/forecast/refresh", { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["forecast"] }),
  });

  if (!can("forecast.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading snapshots" />;
  if (query.isError) return <ErrorState message="Forecast could not be assembled." />;
  const rows = query.data ?? [];
  const latest = rows[0];

  return (
    <div>
      <PageHeader
        eyebrow="Phase 15"
        title="Forecast"
        subtitle="Committed, pipeline, and weighted values come from open opportunities. Win rate is won / decided. Not ML."
        actions={<Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>Snapshot now</Button>}
      />
      {latest ? (
        <div className="mb-6 grid gap-4 md:grid-cols-4">
          {[
            ["Committed", money(latest.committed)],
            ["Weighted", money(latest.weighted)],
            ["Pipeline", money(latest.pipeline)],
            ["Win rate", pct(latest.win_rate)],
          ].map(([label, value]) => (
            <div key={label} className="panel p-5">
              <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">{label}</p>
              <p className="mt-3 text-3xl font-semibold text-navy">{value}</p>
            </div>
          ))}
        </div>
      ) : null}
      {rows.length === 0 ? (
        <EmptyState title="No snapshots" body="Take a snapshot. The API will not invent coverage." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "period", header: "Period", cell: (row) => row.period },
            { key: "committed", header: "Committed", cell: (row) => money(row.committed) },
            { key: "weighted", header: "Weighted", cell: (row) => money(row.weighted) },
            { key: "win", header: "Win rate", cell: (row) => pct(row.win_rate) },
            { key: "ver", header: "Version", cell: (row) => <Badge>{row.version}</Badge> },
          ]}
        />
      )}
    </div>
  );
}
