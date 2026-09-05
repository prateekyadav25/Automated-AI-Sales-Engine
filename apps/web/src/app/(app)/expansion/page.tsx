"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, money } from "@/lib/format";
import type { Whitespace } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export default function ExpansionPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["expansion"],
    queryFn: async () => (await api<Whitespace[]>("/api/v1/lifecycle/expansion")).data ?? [],
    enabled: can("success.read"),
  });
  const refresh = useMutation({
    mutationFn: () => api("/api/v1/lifecycle/expansion/refresh", { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["expansion"] }),
  });

  if (!can("success.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading whitespace" />;
  if (query.isError) return <ErrorState message="Expansion could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Phase 19"
        title="Expansion"
        subtitle="Whitespace is account × catalog with a rules propensity. Value hint is list price, not invented ARR."
        actions={can("success.write") ? <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>Map catalog</Button> : null}
      />
      {rows.length === 0 ? (
        <EmptyState title="No whitespace" body="Map the catalog against accounts. Empty cells stay empty." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "account", header: "Account", cell: (row) => row.account_name },
            { key: "product", header: "Product", cell: (row) => row.product_name },
            { key: "status", header: "Status", cell: (row) => <Badge>{labelize(row.status)}</Badge> },
            { key: "prop", header: "Propensity", cell: (row) => String(row.propensity) },
            { key: "value", header: "List hint", cell: (row) => money(row.value_hint) },
          ]}
        />
      )}
    </div>
  );
}
