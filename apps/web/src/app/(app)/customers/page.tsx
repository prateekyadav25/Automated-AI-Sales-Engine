"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, money } from "@/lib/format";
import type { Customer } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";

export default function CustomersPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["customers"],
    queryFn: async () => (await api<Customer[]>("/api/v1/customers")).data ?? [],
    enabled: can("accounts.read"),
  });
  if (!can("accounts.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message="Customers could not be assembled." />;
  const rows = query.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Close"
        title="Customers"
        subtitle="Closed Won mints the customer, renewal stub, onboarding plan, and a rules-v1 health score."
      />
      {rows.length === 0 ? (
        <EmptyState title="No customers yet" body="Close an opportunity as won to mint a customer and a renewal stub." />
      ) : (
        <DataTable
          rows={rows}
          href={(row) => `/accounts/${row.account_id}`}
          columns={[
            { key: "name", header: "Account", cell: (row) => row.account_name || row.id.slice(0, 8) },
            { key: "status", header: "Status", cell: (row) => <Badge tone="ok">{labelize(row.status)}</Badge> },
            { key: "arr", header: "ARR", cell: (row) => money(row.arr) },
          ]}
        />
      )}
    </div>
  );
}
