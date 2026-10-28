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
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

type CampaignForm = {
  name: string;
  channel: string;
  objective: string;
  budget: string;
  notes: string;
  operating_plan_id: string;
  creative_version_id: string;
  audience: string;
  geography: string;
  placements: string;
  timezone: string;
  currency: string;
  headline: string;
  body: string;
  call_to_action: string;
  asset_ref: string;
  destination: string;
  start_date: string;
  end_date: string;
};

export default function CampaignsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<CampaignForm>({
    defaultValues: {
      name: "",
      channel: "outbound",
      objective: "pipeline",
      budget: "0",
      notes: "",
      operating_plan_id: "",
      creative_version_id: "",
      audience: "",
      geography: "",
      placements: "facebook_feed",
      timezone: "Asia/Kolkata",
      currency: "INR",
      headline: "",
      body: "",
      call_to_action: "LEARN_MORE",
      asset_ref: "",
      destination: "website_form",
      start_date: "",
      end_date: "",
    },
  });
  const channel = form.watch("channel");
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
    mutationFn: (body: CampaignForm) => {
      const payload: Record<string, unknown> = {
        name: body.name,
        channel: body.channel,
        objective: body.channel === "meta" ? "traffic" : body.objective,
        budget: Number(body.budget),
        notes: body.notes,
      };
      if (body.channel === "meta") {
        Object.assign(payload, {
          operating_plan_id: body.operating_plan_id,
          creative_version_id: body.creative_version_id,
          audience: body.audience,
          geography: body.geography,
          placements: body.placements,
          timezone: body.timezone,
          currency: body.currency,
          headline: body.headline,
          body: body.body,
          call_to_action: body.call_to_action,
          asset_ref: body.asset_ref,
          destination: "website_form",
          start_date: body.start_date,
          end_date: body.end_date,
        });
      }
      return api("/api/v1/lifecycle/campaigns", { method: "POST", body: JSON.stringify(payload) });
    },
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
  const pause = useMutation({
    mutationFn: (id: string) => api(`/api/v1/lifecycle/campaigns/${id}/pause`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaigns"] });
      void client.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
  const sync = useMutation({
    mutationFn: (id: string) => api(`/api/v1/lifecycle/campaigns/${id}/sync`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["campaigns"] }),
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
        subtitle="Named motions with a budget ledger. Derived CTR, CPC, and CPL persist only after a live metrics sync. Launch and pause stay approval-gated."
        actions={can("campaigns.write") ? <Button onClick={() => setOpen(true)}>New campaign</Button> : null}
      />
      {rows.length === 0 ? (
        <EmptyState title="No campaigns" body="Create a motion. Empty stays empty." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "Campaign", cell: (row) => <Link href={`/campaigns/${row.id}`}>{row.name}</Link> },
            { key: "channel", header: "Channel", cell: (row) => labelize(row.channel) },
            { key: "status", header: "Status", cell: (row) => <Badge tone="gold">{labelize(row.status)}</Badge> },
            { key: "budget", header: "Budget", cell: (row) => money(row.budget) },
            { key: "spent", header: "Spent", cell: (row) => money(row.spent) },
            { key: "ctr", header: "CTR", cell: (row) => row.ctr ?? "—" },
            { key: "cpc", header: "CPC", cell: (row) => row.cpc ? money(row.cpc) : "—" },
            { key: "cpl", header: "CPL", cell: (row) => row.cpl ? money(row.cpl) : "—" },
            {
              key: "actions",
              header: "",
              cell: (row) =>
                can("campaigns.write") && (row.channel === "linkedin" || row.channel === "instagram") ? (
                  <div className="flex flex-wrap gap-2">
                    {row.status !== "launched" ? (
                      <Button variant="line" onClick={() => launch.mutate(row.id)} disabled={launch.isPending}>
                        Launch
                      </Button>
                    ) : (
                      <Button variant="line" onClick={() => pause.mutate(row.id)} disabled={pause.isPending}>
                        Pause
                      </Button>
                    )}
                    <Button variant="line" onClick={() => sync.mutate(row.id)} disabled={sync.isPending}>
                      Sync
                    </Button>
                  </div>
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
              <Select {...form.register("channel", { onChange: (event) => { if (event.target.value === "meta") form.setValue("objective", "traffic"); } })}>
                <option value="outbound">Outbound</option>
                <option value="linkedin">LinkedIn</option>
                <option value="instagram">Instagram</option>
                <option value="meta">Meta</option>
              </Select>
            </Field>
            <Field label="Objective">
              {channel === "meta" ? (
                <Select {...form.register("objective")}>
                  <option value="traffic">Website traffic</option>
                </Select>
              ) : (
                <Input {...form.register("objective")} />
              )}
            </Field>
          </div>
          <Field label={channel === "meta" ? "Proposed budget" : "Budget"}>
            <Input type="number" {...form.register("budget")} />
          </Field>
          {channel === "meta" ? (
            <>
              <p className="text-sm text-[var(--muted)]">This amount is a proposal. Saving it does not authorize spend or activation.</p>
              <Field label="Operating plan id"><Input {...form.register("operating_plan_id", { required: true })} /></Field>
              <Field label="Creative version id"><Input {...form.register("creative_version_id", { required: true })} /></Field>
              <Field label="Audience"><Input {...form.register("audience", { required: true })} /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Geography"><Input {...form.register("geography", { required: true })} placeholder="IN" /></Field>
                <Field label="Time zone"><Input {...form.register("timezone", { required: true })} /></Field>
              </div>
              <Field label="Placement">
                <Select {...form.register("placements")}>
                  <option value="facebook_feed">Facebook feed</option>
                </Select>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Start"><Input type="date" {...form.register("start_date", { required: true })} /></Field>
                <Field label="End"><Input type="date" {...form.register("end_date", { required: true })} /></Field>
              </div>
              <Field label="Currency"><Input {...form.register("currency", { required: true })} /></Field>
              <Field label="Headline"><Input {...form.register("headline", { required: true })} /></Field>
              <Field label="Copy"><Textarea rows={3} {...form.register("body", { required: true })} /></Field>
              <Field label="Call to action">
                <Select {...form.register("call_to_action")}>
                  <option value="LEARN_MORE">Learn more</option>
                  <option value="SIGN_UP">Sign up</option>
                  <option value="CONTACT_US">Contact us</option>
                </Select>
              </Field>
              <Field label="Creative asset"><Input {...form.register("asset_ref", { required: true })} /></Field>
              <Field label="Destination">
                <Select {...form.register("destination")}>
                  <option value="website_form">Website capture form</option>
                </Select>
              </Field>
            </>
          ) : null}
          <Field label="Notes"><Textarea rows={3} {...form.register("notes")} /></Field>
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
    </div>
  );
}
