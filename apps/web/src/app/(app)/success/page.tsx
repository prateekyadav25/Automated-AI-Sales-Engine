"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, money } from "@/lib/format";
import type { SuccessRow } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

export default function SuccessPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["success"],
    queryFn: async () => (await api<SuccessRow[]>("/api/v1/lifecycle/success")).data ?? [],
    enabled: can("success.read"),
  });
  const rescore = useMutation({
    mutationFn: (customerId: string) => api(`/api/v1/lifecycle/success/health/${customerId}`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["success"] }),
  });

  if (!can("success.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading the book of record" />;
  if (query.isError) return <ErrorState message="Success could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Phases 16–17"
        title="Success"
        subtitle="Onboarding plans and health scores mint from Closed Won. Usage is a labeled mock provider."
      />
      {rows.length === 0 ? (
        <EmptyState title="No customers" body="Close a deal as won. This desk will not invent health." />
      ) : (
        <DataTable
          rows={rows.map((row) => ({ ...row, id: row.customer.id }))}
          columns={[
            { key: "name", header: "Account", cell: (row) => <Link href={`/accounts/${row.account_id}`} className="text-brand">{row.account_name}</Link> },
            { key: "arr", header: "ARR", cell: (row) => money(row.arr) },
            { key: "onb", header: "Onboarding", cell: (row) => labelize(row.onboarding_status) || "—" },
            { key: "health", header: "Health", cell: (row) => <Badge tone={(row.health?.total ?? 0) < 50 ? "gold" : "ok"}>{row.health?.total ?? "—"}</Badge> },
            { key: "ver", header: "Version", cell: (row) => row.health?.version ?? "—" },
            {
              key: "act",
              header: "",
              cell: (row) =>
                can("success.write") ? (
                  <Button variant="line" onClick={(event) => { event.preventDefault(); rescore.mutate(row.customer.id); }}>
                    Rescore
                  </Button>
                ) : null,
            },
          ]}
        />
      )}
    </div>
  );
}
