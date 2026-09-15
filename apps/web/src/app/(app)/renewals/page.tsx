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
import Link from "next/link";

export default function RenewalsPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["renewals"],
    queryFn: async () => (await api<RenewalRow[]>("/api/v1/lifecycle/renewals")).data ?? [],
    enabled: can("success.read"),
    refetchInterval: 5000,
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
        subtitle="Windows, readiness, and a commercial baseline from the contract. Unknown term or escalation stays null."
      />
      {rows.length === 0 ? (
        <EmptyState title="No renewals" body="Win a deal to mint the first stub." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            {
              key: "name",
              header: "Account",
              cell: (row) =>
                row.customer_id ? <Link href={`/customers/${row.customer_id}`} className="text-brand">{row.account_name || "—"}</Link> : row.account_name || "—",
            },
            { key: "arr", header: "Current ARR", cell: (row) => money(row.current_arr) },
            { key: "date", header: "Renewal", cell: (row) => when(row.renewal_date) },
            {
              key: "ready",
              header: "Readiness",
              cell: (row) => (
                <span>
                  {String(row.readiness ?? "—")}
                  {row.why_ready?.length ? <span className="block text-[11px] text-[var(--muted)]">Ready: {row.why_ready.join("; ")}</span> : null}
                  {row.why_at_risk?.length ? <span className="block text-[11px] text-[var(--muted)]">At risk: {row.why_at_risk.join("; ")}</span> : null}
                </span>
              ),
            },
            { key: "base", header: "Baseline", cell: (row) => row.baseline_amount == null ? row.baseline_status || "needs_review" : money(row.baseline_amount) },
            { key: "status", header: "Status", cell: (row) => <Badge>{labelize(row.stage || row.status)}</Badge> },
          ]}
        />
      )}
    </div>
  );
}
