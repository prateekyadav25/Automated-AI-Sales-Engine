"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { DealInsight } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

export default function DealsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["deals"],
    queryFn: async () => (await api<DealInsight[]>("/api/v1/lifecycle/deals")).data ?? [],
    enabled: can("deals.read"),
  });
  const rescore = useMutation({
    mutationFn: () => api("/api/v1/lifecycle/deals/rescore", { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["deals"] }),
  });

  if (!can("deals.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Scoring the book" />;
  if (query.isError) return <ErrorState message="Deal intelligence could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Phase 13"
        title="Deal intelligence"
        subtitle="Rules-v1 flags: missing buyer, weak champion, stall, close-date slip, competitor, empty next step."
        actions={<Button onClick={() => rescore.mutate()} disabled={rescore.isPending}>Rescore book</Button>}
      />
      {rows.length === 0 ? (
        <EmptyState title="No insights yet" body="Open opportunities get a risk card when you rescore." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            {
              key: "name",
              header: "Opportunity",
              cell: (row) => <Link href={`/opportunities/${row.opportunity_id}`} className="text-brand">{row.opportunity_name || row.opportunity_id.slice(0, 8)}</Link>,
            },
            { key: "risk", header: "Risk", cell: (row) => <Badge tone={row.risk_score >= 40 ? "gold" : "ok"}>{row.risk_score}</Badge> },
            { key: "flags", header: "Flags", cell: (row) => [row.missing_buyer && "buyer", row.stall && "stall", row.close_slip && "slip"].filter(Boolean).join(" · ") || "—" },
            { key: "why", header: "Why", cell: (row) => row.reasons },
            { key: "ver", header: "Version", cell: (row) => row.version },
          ]}
        />
      )}
    </div>
  );
}
