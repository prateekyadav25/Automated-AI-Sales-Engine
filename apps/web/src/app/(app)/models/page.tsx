"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { ModelCard } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";

export default function ModelsPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["models"],
    queryFn: async () => (await api<ModelCard[]>("/api/v1/lifecycle/models")).data ?? [],
    enabled: can("revops.read"),
  });
  if (!can("revops.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading model cards" />;
  if (query.isError) return <ErrorState message="Model cards could not be assembled." />;
  const rows = query.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Phase 21"
        title="Model cards"
        subtitle="These are production rules, not trained models. last_trained is null. No invented accuracy."
      />
      {rows.length === 0 ? (
        <EmptyState title="No cards" body="Rules-v1 cards appear when scoring engines are commissioned." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "Card", cell: (row) => row.name },
            { key: "purpose", header: "Purpose", cell: (row) => row.purpose },
            { key: "ver", header: "Version", cell: (row) => <Badge>{row.version}</Badge> },
            { key: "status", header: "Status", cell: (row) => row.status },
            { key: "notes", header: "Notes", cell: (row) => row.notes },
          ]}
        />
      )}
    </div>
  );
}
