"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { StatusPill } from "@/components/workspace-ui";
import { useAuth } from "@/lib/auth";
import type { SuccessRow } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

export default function OnboardingPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["success"],
    queryFn: async () => (await api<SuccessRow[]>("/api/v1/lifecycle/success")).data ?? [],
    enabled: can("success.read"),
  });
  if (!can("success.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Loading onboarding" />;
  if (query.isError) return <ErrorState message="Onboarding could not be loaded." />;
  const rows = (query.data ?? []).map((row) => ({ ...row, id: row.customer.id }));
  return (
    <div>
      <PageHeader
        eyebrow="Customers"
        title="Onboarding"
        subtitle="Milestones come from the success record. A missing date stays open."
        nextHref="/success"
        nextLabel="Success"
      />
      {rows.length === 0 ? (
        <EmptyState title="No customers to onboard" body="Close a won opportunity before onboarding starts." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "Customer", cell: (row) => <Link href={`/customers/${row.customer.id}`}>{row.account_name}</Link> },
            {
              key: "status",
              header: "Milestone",
              cell: (row) => (
                <StatusPill tone={row.onboarding_status === "complete" ? "success" : "review"}>{row.onboarding_status || "Not started"}</StatusPill>
              ),
            },
            { key: "renewal", header: "Renewal", cell: (row) => row.renewal_date || "Not recorded" },
          ]}
        />
      )}
    </div>
  );
}
