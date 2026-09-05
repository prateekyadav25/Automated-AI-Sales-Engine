"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Drawer, Field, FormActions, Input, Score, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import type { Market } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

type Overview = { markets: number; signals: number; triggers: number; mock_signals: number; scored_markets: number };

export default function MarketPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm({ defaultValues: { name: "", industry: "", geography: "", description: "" } });
  const overview = useQuery({
    queryKey: ["market-overview"],
    queryFn: async () => (await api<Overview>("/api/v1/market/overview")).data,
    enabled: can("markets.read"),
  });
  const query = useQuery({
    queryKey: ["markets"],
    queryFn: async () => (await api<Market[]>("/api/v1/market")).data ?? [],
    enabled: can("markets.read"),
  });
  const create = useMutation({
    mutationFn: (body: { name: string; industry: string; geography: string; description: string }) =>
      api("/api/v1/market", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["markets"] });
      void client.invalidateQueries({ queryKey: ["market-overview"] });
      setOpen(false);
      form.reset();
    },
  });
  const refresh = useMutation({
    mutationFn: () => api("/api/v1/market/refresh", { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["market-overview"] });
    },
  });

  if (!can("markets.read")) return <DeniedState />;
  if (query.isLoading || overview.isLoading) return <LoadingState label="Reading the market floor" />;
  if (query.isError || overview.isError) return <ErrorState message="Market intelligence could not be assembled." />;
  const rows = query.data ?? [];
  const k = overview.data;

  return (
    <div>
      <PageHeader
        eyebrow="Phase 7"
        title="Market Intelligence"
        subtitle="Attractiveness and timing are scored in code. Providers are labeled mock until a live vendor is configured."
        actions={
          <>
            <Link href="/market/signals" className="text-sm text-brand">Signals</Link>
            <Link href="/market/triggers" className="text-sm text-brand">Triggers</Link>
            {can("signals.write") ? (
              <Button variant="line" onClick={() => refresh.mutate()}>
                {refresh.isPending ? "Refreshing…" : "Refresh mock providers"}
              </Button>
            ) : null}
            {can("markets.write") ? <Button onClick={() => setOpen(true)}>Define a market</Button> : null}
          </>
        }
      />
      {k ? (
        <div className="mb-6 grid gap-4 md:grid-cols-4">
          {[
            ["Markets", String(k.markets), "Defined theses"],
            ["Scored", String(k.scored_markets), "rules-v1"],
            ["Signals", String(k.signals), `${k.mock_signals} labeled mock`],
            ["Triggers", String(k.triggers), "Buying events"],
          ].map(([label, value, hint]) => (
            <div key={label} className="panel p-5">
              <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">{label}</p>
              <p className="mt-3 text-3xl font-semibold text-navy">{value}</p>
              <p className="mt-2 text-xs text-[var(--muted)]">{hint}</p>
            </div>
          ))}
        </div>
      ) : null}
      {rows.length === 0 ? (
        <EmptyState title="No markets yet" body="Define a thesis. Scores stay at zero until signals exist." />
      ) : (
        <DataTable
          rows={rows}
          href={(row) => `/market/${row.id}`}
          columns={[
            { key: "name", header: "Market", cell: (row) => row.name },
            { key: "industry", header: "Industry", cell: (row) => labelize(row.industry) },
            { key: "geo", header: "Geography", cell: (row) => row.geography || "—" },
            { key: "attr", header: "Attractiveness", cell: (row) => <Score value={row.attractiveness} /> },
            { key: "timing", header: "Timing", cell: (row) => <Score value={row.buying_timing} /> },
            { key: "comp", header: "Competition", cell: (row) => <Badge>{row.competitive_intensity}</Badge> },
          ]}
        />
      )}
      <Drawer open={open} title="Define a market" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <Field label="Name"><Input {...form.register("name", { required: true })} /></Field>
          <Field label="Industry"><Input {...form.register("industry")} /></Field>
          <Field label="Geography"><Input {...form.register("geography")} /></Field>
          <Field label="Description"><Textarea rows={4} {...form.register("description")} /></Field>
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} label="Create and score" />
        </form>
      </Drawer>
    </div>
  );
}
