"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, when } from "@/lib/format";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";

type Audit = { id: string; action: string; entity_type: string; actor_type: string; created_at: string };

export default function AuditPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["audit"],
    queryFn: async () => (await api<Audit[]>("/api/v1/admin/audit")).data ?? [],
    enabled: can("audit.read"),
  });
  if (!can("audit.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message="Audit could not be assembled." />;
  const rows = query.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="House"
        title="Audit"
        subtitle="Human and machine mutations, last one hundred events, tenant-scoped."
      />
      {rows.length === 0 ? (
        <EmptyState title="No audit events yet" body="Login and writes create audit rows." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "action", header: "Action", cell: (row) => row.action },
            { key: "entity", header: "Entity", cell: (row) => labelize(row.entity_type) },
            {
              key: "actor",
              header: "Actor",
              cell: (row) => <Badge>{labelize(row.actor_type)}</Badge>,
            },
            { key: "when", header: "When", cell: (row) => when(row.created_at) },
          ]}
        />
      )}
    </div>
  );
}
