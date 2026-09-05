"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Drawer, Field, FormActions, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import type { Account, AdvocacyAsset, Referral } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

export default function AdvocacyPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<{ account_id: string; kind: string; readiness: number; notes: string }>({
    defaultValues: { account_id: "", kind: "reference", readiness: 40, notes: "" },
  });
  const query = useQuery({
    queryKey: ["advocacy"],
    queryFn: async () => (await api<{ assets: AdvocacyAsset[]; referrals: Referral[] }>("/api/v1/lifecycle/advocacy")).data,
    enabled: can("advocacy.read"),
  });
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: async () => (await api<Account[]>("/api/v1/accounts")).data ?? [],
    enabled: can("accounts.read") && open,
  });
  const create = useMutation({
    mutationFn: (body: { account_id: string; kind: string; readiness: number; notes: string }) =>
      api("/api/v1/lifecycle/advocacy", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["advocacy"] });
      setOpen(false);
    },
  });

  if (!can("advocacy.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading advocacy" />;
  if (query.isError) return <ErrorState message="Advocacy could not be assembled." />;
  const assets = query.data?.assets ?? [];
  const referrals = query.data?.referrals ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Phase 20"
        title="Advocacy"
        subtitle="References and referrals are identified, not invented reviews. Readiness is a human score."
        actions={can("advocacy.write") ? <Button onClick={() => setOpen(true)}>Add asset</Button> : null}
      />
      {assets.length === 0 ? (
        <EmptyState title="No advocacy assets" body="Identify a reference. Do not mint a case study that was never approved." />
      ) : (
        <DataTable
          rows={assets}
          columns={[
            { key: "kind", header: "Kind", cell: (row) => labelize(row.kind) },
            { key: "ready", header: "Readiness", cell: (row) => String(row.readiness) },
            { key: "status", header: "Status", cell: (row) => <Badge>{labelize(row.status)}</Badge> },
            { key: "notes", header: "Notes", cell: (row) => row.notes || "—" },
          ]}
        />
      )}
      <h2 className="mb-3 mt-8 text-xl font-semibold text-navy">Referrals</h2>
      {referrals.length === 0 ? (
        <EmptyState title="No referrals" body="A referral waits for a name." />
      ) : (
        <DataTable
          rows={referrals}
          columns={[
            { key: "name", header: "Referred", cell: (row) => row.referred_name },
            { key: "email", header: "Email", cell: (row) => row.email || "—" },
            { key: "status", header: "Status", cell: (row) => <Badge>{labelize(row.status)}</Badge> },
          ]}
        />
      )}
      <Drawer open={open} title="Advocacy asset" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate({ ...values, readiness: Number(values.readiness) }))} className="space-y-4">
          <Field label="Account">
            <Select {...form.register("account_id", { required: true })}>
              <option value="">Select</option>
              {(accounts.data ?? []).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </Select>
          </Field>
          <Field label="Kind"><Input {...form.register("kind")} /></Field>
          <Field label="Readiness"><Input type="number" {...form.register("readiness", { valueAsNumber: true })} /></Field>
          <Field label="Notes"><Textarea rows={3} {...form.register("notes")} /></Field>
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
    </div>
  );
}
