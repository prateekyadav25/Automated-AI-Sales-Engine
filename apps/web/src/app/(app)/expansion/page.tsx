"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, money } from "@/lib/format";
import type { ExpansionRec, Whitespace } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export default function ExpansionPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["expansion"],
    queryFn: async () => (await api<Whitespace[]>("/api/v1/lifecycle/expansion")).data ?? [],
    enabled: can("success.read"),
    refetchInterval: 5000,
  });
  const recs = useQuery({
    queryKey: ["expansion-recs"],
    queryFn: async () => (await api<ExpansionRec[]>("/api/v1/post-sale/expansion")).data ?? [],
    enabled: can("success.read"),
    refetchInterval: 5000,
  });
  const refresh = useMutation({
    mutationFn: () => api("/api/v1/lifecycle/expansion/refresh", { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["expansion"] });
      void client.invalidateQueries({ queryKey: ["expansion-recs"] });
    },
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
        subtitle="Whitespace is account × catalog. Recommendations stay evidence-only. Amount is null until known."
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
      <h2 className="mb-3 mt-8 text-xl font-semibold text-navy">Recommendations</h2>
      {(recs.data ?? []).length === 0 ? (
        <EmptyState title="No expansion recommendations" body="Autopilot writes recommendations from whitespace and catalog adjacency. It does not mint opportunities." />
      ) : (
        <DataTable
          rows={recs.data ?? []}
          columns={[
            { key: "title", header: "Title", cell: (row) => row.title },
            { key: "kind", header: "Kind", cell: (row) => labelize(row.kind) },
            { key: "conf", header: "Confidence", cell: (row) => String(row.confidence) },
            { key: "amount", header: "Amount", cell: (row) => row.amount ?? "null" },
            { key: "status", header: "Status", cell: (row) => <Badge>{labelize(row.status)}</Badge> },
            { key: "evidence", header: "Evidence", cell: (row) => row.reason || "—" },
            {
              key: "feedback",
              header: "Feedback",
              cell: (row) =>
                can("success.write") ? (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      onClick={() =>
                        api(`/api/v1/post-sale/expansion/${row.id}/feedback`, {
                          method: "POST",
                          body: JSON.stringify({ action: "ignored", note: "ui" }),
                        }).then(() => client.invalidateQueries({ queryKey: ["expansion-recs"] }))
                      }
                    >
                      Ignore
                    </Button>
                    <Button
                      variant="line"
                      onClick={() =>
                        api(`/api/v1/post-sale/expansion/${row.id}/outcome`, {
                          method: "POST",
                          body: JSON.stringify({ status: "won", value: null, product: "" }),
                        }).then(() => client.invalidateQueries({ queryKey: ["expansion-recs"] }))
                      }
                    >
                      Won
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() =>
                        api(`/api/v1/post-sale/expansion/${row.id}/useful`, {
                          method: "POST",
                          body: JSON.stringify({ useful: "YES" }),
                        }).then(() => client.invalidateQueries({ queryKey: ["expansion-recs"] }))
                      }
                    >
                      Useful
                    </Button>
                  </div>
                ) : (
                  "—"
                ),
            },
          ]}
        />
      )}
    </div>
  );
}
