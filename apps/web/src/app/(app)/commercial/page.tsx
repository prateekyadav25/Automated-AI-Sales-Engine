"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Drawer, Field, FormActions, Input, Select } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { money } from "@/lib/format";
import type { Opportunity, Product, Quote } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type QuoteForm = { opportunity_id: string; product_id: string; quantity: number; discount_pct: number; tax_pct: number };

export default function CommercialPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<QuoteForm>({ defaultValues: { opportunity_id: "", product_id: "", quantity: 1, discount_pct: 0, tax_pct: 0 } });
  const products = useQuery({
    queryKey: ["products"],
    queryFn: async () => (await api<Product[]>("/api/v1/lifecycle/products")).data ?? [],
    enabled: can("commercial.read"),
  });
  const quotes = useQuery({
    queryKey: ["quotes"],
    queryFn: async () => (await api<Quote[]>("/api/v1/lifecycle/quotes")).data ?? [],
    enabled: can("commercial.read"),
  });
  const opps = useQuery({
    queryKey: ["opportunities"],
    queryFn: async () => (await api<Opportunity[]>("/api/v1/opportunities")).data ?? [],
    enabled: can("opportunities.read") && open,
  });
  const create = useMutation({
    mutationFn: (body: QuoteForm) =>
      api("/api/v1/lifecycle/quotes", {
        method: "POST",
        body: JSON.stringify({
          opportunity_id: body.opportunity_id,
          discount_pct: Number(body.discount_pct),
          tax_pct: Number(body.tax_pct),
          lines: [{ product_id: body.product_id, quantity: Number(body.quantity) }],
        }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["quotes"] });
      void client.invalidateQueries({ queryKey: ["approvals"] });
      setOpen(false);
    },
  });

  if (!can("commercial.read")) return <DeniedState />;
  if (products.isLoading || quotes.isLoading) return <LoadingState label="Reading the catalog" />;
  if (products.isError || quotes.isError) return <ErrorState message="Commercial could not be assembled." />;

  return (
    <div>
      <PageHeader
        eyebrow="Phase 14"
        title="Commercial"
        subtitle="Line totals are quantity × list price. Discount ≥ 10% queues Approvals. The model does not invent ARR."
        actions={can("commercial.write") ? <Button onClick={() => setOpen(true)}>New quote</Button> : null}
      />
      <h2 className="mb-3 text-xl font-semibold text-navy">Catalog</h2>
      {(products.data ?? []).length === 0 ? (
        <EmptyState title="No products" body="Add SKUs before quoting." />
      ) : (
        <DataTable
          rows={products.data ?? []}
          columns={[
            { key: "sku", header: "SKU", cell: (row) => row.sku },
            { key: "name", header: "Product", cell: (row) => row.name },
            { key: "price", header: "List", cell: (row) => money(row.list_price) },
          ]}
        />
      )}
      <h2 className="mb-3 mt-8 text-xl font-semibold text-navy">Quotes</h2>
      {(quotes.data ?? []).length === 0 ? (
        <EmptyState title="No quotes" body="A quote is math, not a story." />
      ) : (
        <DataTable
          rows={quotes.data ?? []}
          columns={[
            { key: "id", header: "Quote", cell: (row) => row.id.slice(0, 8) },
            { key: "sub", header: "Subtotal", cell: (row) => money(row.subtotal) },
            { key: "disc", header: "Discount", cell: (row) => `${row.discount_pct}%` },
            { key: "total", header: "Total", cell: (row) => money(row.total) },
            { key: "appr", header: "Approval", cell: (row) => <Badge tone={row.approval_required ? "gold" : "ok"}>{row.approval_required ? "queued" : "none"}</Badge> },
          ]}
        />
      )}
      <Drawer open={open} title="New quote" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <Field label="Opportunity">
            <Select {...form.register("opportunity_id", { required: true })}>
              <option value="">Select</option>
              {(opps.data ?? []).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </Select>
          </Field>
          <Field label="Product">
            <Select {...form.register("product_id", { required: true })}>
              <option value="">Select</option>
              {(products.data ?? []).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </Select>
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Qty"><Input type="number" {...form.register("quantity", { valueAsNumber: true })} /></Field>
            <Field label="Discount %"><Input type="number" {...form.register("discount_pct", { valueAsNumber: true })} /></Field>
            <Field label="Tax %"><Input type="number" {...form.register("tax_pct", { valueAsNumber: true })} /></Field>
          </div>
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
    </div>
  );
}
