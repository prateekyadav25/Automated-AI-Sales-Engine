"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, money, when } from "@/lib/format";
import type { RenewalRow } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";

export default function RenewalsPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["renewals"],
    queryFn: async () => (await api<RenewalRow[]>("/api/v1/lifecycle/renewals")).data ?? [],
    enabled: can("success.read"),
  });
  if (!can("success.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading renewals" />;
  if (query.isError) return <ErrorState message="Renewals could not be assembled." />;
  const rows = query.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Phase 18"
        title="Renewals"
        subtitle="Stubs mint on Closed Won. GRR/NRR stay 1.0 until amendments exist. No invented contraction."
      />
      {rows.length === 0 ? (
        <EmptyState title="No renewals" body="Win a deal to mint the first stub." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "Account", cell: (row) => row.account_name || "—" },
            { key: "arr", header: "Current ARR", cell: (row) => money(row.current_arr) },
            { key: "date", header: "Renewal", cell: (row) => when(row.renewal_date) },
            { key: "status", header: "Status", cell: (row) => <Badge>{labelize(row.status)}</Badge> },
          ]}
        />
      )}
    </div>
  );
}
