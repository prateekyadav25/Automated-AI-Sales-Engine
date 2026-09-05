"use client";

import { DataTable } from "@/components/data-table";
import { ListToolbar } from "@/components/list-toolbar";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Drawer, Field, FormActions, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { OWNERSHIP, TIERS } from "@/lib/constants";
import { labelize } from "@/lib/format";
import { qs, useDebounced } from "@/lib/hooks";
import type { Account } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type AccountForm = {
  name: string;
  industry: string;
  website: string;
  domain: string;
  hq_country: string;
  employee_count: number | null;
  annual_revenue: string;
  ownership: string;
  target_tier: string;
  notes: string;
};

export default function AccountsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const search = useDebounced(q);
  const form = useForm<AccountForm>({
    defaultValues: {
      name: "",
      industry: "",
      website: "",
      domain: "",
      hq_country: "",
      employee_count: null,
      annual_revenue: "",
      ownership: "prospect",
      target_tier: "tier_2",
      notes: "",
    },
  });

  const query = useQuery({
    queryKey: ["accounts", search, page],
    queryFn: () => api<Account[]>(`/api/v1/accounts${qs({ q: search, page, page_size: 25 })}`),
    enabled: can("accounts.read"),
  });

  const create = useMutation({
    mutationFn: (body: AccountForm) =>
      api("/api/v1/accounts", {
        method: "POST",
        body: JSON.stringify({
          ...body,
          employee_count: body.employee_count ? Number(body.employee_count) : null,
          annual_revenue: body.annual_revenue || null,
        }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["accounts"] });
      setOpen(false);
      form.reset();
    },
  });

  if (!can("accounts.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Opening the book" />;
  if (query.isError) return <ErrorState message="Accounts could not be assembled." />;
  const rows = query.data?.data ?? [];
  const total = query.data?.meta?.total ?? rows.length;

  return (
    <div>
      <PageHeader
        eyebrow="House book"
        title="Accounts"
        subtitle="One record per company. A customer is minted only when an opportunity is Closed Won."
      />
      <ListToolbar
        query={q}
        onQuery={(value) => {
          setQ(value);
          setPage(1);
        }}
        onCreate={can("accounts.write") ? () => setOpen(true) : undefined}
        createLabel="Open an account"
      />
      {rows.length === 0 ? (
        <EmptyState title="The book is empty" body="Seed, import, or create an account. Nothing decorative appears here." />
      ) : (
        <>
          <DataTable
            rows={rows}
            href={(row) => `/accounts/${row.id}`}
            columns={[
              { key: "name", header: "Account", cell: (row) => row.name },
              { key: "industry", header: "Industry", cell: (row) => row.industry || "—" },
              { key: "country", header: "HQ", cell: (row) => row.hq_country || "—" },
              { key: "ownership", header: "Ownership", cell: (row) => <Badge>{labelize(row.ownership)}</Badge> },
              { key: "tier", header: "Tier", cell: (row) => labelize(row.target_tier) },
            ]}
          />
          <Pagination page={page} pageSize={25} total={total} onPage={setPage} />
        </>
      )}
      <Drawer open={open} title="Open an account" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <Field label="Name"><Input {...form.register("name", { required: true })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Industry"><Input {...form.register("industry")} /></Field>
            <Field label="HQ country"><Input {...form.register("hq_country")} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Website"><Input {...form.register("website")} /></Field>
            <Field label="Domain"><Input {...form.register("domain")} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Employees"><Input type="number" {...form.register("employee_count")} /></Field>
            <Field label="Annual revenue"><Input {...form.register("annual_revenue")} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Ownership">
              <Select {...form.register("ownership")}>
                {OWNERSHIP.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
              </Select>
            </Field>
            <Field label="Tier">
              <Select {...form.register("target_tier")}>
                {TIERS.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
              </Select>
            </Field>
          </div>
          <Field label="Notes"><Textarea rows={4} {...form.register("notes")} /></Field>
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} label="Create account" />
        </form>
      </Drawer>
    </div>
  );
}
