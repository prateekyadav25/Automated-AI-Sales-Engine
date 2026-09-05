"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Drawer, Field, FormActions, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, money } from "@/lib/format";
import type { Campaign } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type CampaignForm = { name: string; channel: string; objective: string; budget: string; notes: string };

export default function CampaignsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<CampaignForm>({ defaultValues: { name: "", channel: "outbound", objective: "pipeline", budget: "0", notes: "" } });
  const query = useQuery({
    queryKey: ["campaigns"],
    queryFn: async () => (await api<Campaign[]>("/api/v1/lifecycle/campaigns")).data ?? [],
    enabled: can("campaigns.read"),
  });
  const abm = useQuery({
    queryKey: ["abm"],
    queryFn: async () => (await api<{ name: string; thesis: string; status: string }[]>("/api/v1/lifecycle/abm")).data ?? [],
    enabled: can("campaigns.read"),
  });
  const create = useMutation({
    mutationFn: (body: CampaignForm) =>
      api("/api/v1/lifecycle/campaigns", { method: "POST", body: JSON.stringify({ ...body, budget: Number(body.budget) }) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaigns"] });
      setOpen(false);
      form.reset();
    },
  });
  const launch = useMutation({
    mutationFn: (id: string) => api(`/api/v1/lifecycle/campaigns/${id}/launch`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaigns"] });
      void client.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  if (!can("campaigns.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading campaigns" />;
  if (query.isError) return <ErrorState message="Campaigns could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Phase 9"
        title="Campaigns & ABM"
        subtitle="Named motions with a budget ledger. LinkedIn and Instagram Launch queues Approvals. No fake CTR."
        actions={can("campaigns.write") ? <Button onClick={() => setOpen(true)}>New campaign</Button> : null}
      />
      {rows.length === 0 ? (
        <EmptyState title="No campaigns" body="Create a motion. Empty stays empty." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "Campaign", cell: (row) => row.name },
            { key: "channel", header: "Channel", cell: (row) => labelize(row.channel) },
            { key: "status", header: "Status", cell: (row) => <Badge tone="gold">{labelize(row.status)}</Badge> },
            { key: "budget", header: "Budget", cell: (row) => money(row.budget) },
            { key: "spent", header: "Spent", cell: (row) => money(row.spent) },
            {
              key: "launch",
              header: "",
              cell: (row) =>
                can("campaigns.write") && (row.channel === "linkedin" || row.channel === "instagram") && row.status !== "launched" ? (
                  <Button variant="line" onClick={() => launch.mutate(row.id)} disabled={launch.isPending}>
                    Launch
                  </Button>
                ) : (
                  "—"
                ),
            },
          ]}
        />
      )}
      <h2 className="mb-3 mt-8 text-xl font-semibold text-navy">ABM plays</h2>
      {(abm.data ?? []).length === 0 ? (
        <EmptyState title="No ABM plays" body="Account theses wait until someone writes them." />
      ) : (
        <div className="space-y-3">
          {(abm.data ?? []).map((row) => (
            <article key={row.name} className="panel p-5">
              <p>{row.name}</p>
              <p className="mt-1 text-sm text-[var(--muted)]">{row.thesis}</p>
              <p className="mt-2 text-xs uppercase tracking-[0.16em] text-brand">{labelize(row.status)}</p>
            </article>
          ))}
        </div>
      )}
      <Drawer open={open} title="New campaign" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <Field label="Name"><Input {...form.register("name", { required: true })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Channel">
              <Select {...form.register("channel")}>
                <option value="outbound">Outbound</option>
                <option value="linkedin">LinkedIn</option>
                <option value="instagram">Instagram</option>
              </Select>
            </Field>
            <Field label="Objective"><Input {...form.register("objective")} /></Field>
          </div>
          <Field label="Budget"><Input type="number" {...form.register("budget")} /></Field>
          <Field label="Notes"><Textarea rows={3} {...form.register("notes")} /></Field>
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
    </div>
  );
}
