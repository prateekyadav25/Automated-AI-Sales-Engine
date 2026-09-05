"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { Timeline } from "@/components/timeline";
import { Badge, Button, Drawer, Field, FormActions, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { OPP_STAGES } from "@/lib/constants";
import { labelize, money } from "@/lib/format";
import type { Opportunity } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

export default function OpportunityDetailPage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<Opportunity>();
  const query = useQuery({
    queryKey: ["opportunity", params.id],
    queryFn: async () => (await api<Opportunity>(`/api/v1/opportunities/${params.id}`)).data,
    enabled: can("opportunities.read"),
  });
  const save = useMutation({
    mutationFn: (body: Opportunity) =>
      api(`/api/v1/opportunities/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          account_id: body.account_id,
          name: body.name,
          stage: body.stage,
          amount: body.amount,
          next_step: body.next_step,
          expected_close: body.expected_close || null,
          probability: body.probability,
        }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["opportunity", params.id] });
      setOpen(false);
    },
  });
  const closeWon = useMutation({
    mutationFn: () => api(`/api/v1/opportunities/${params.id}/close-won`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["opportunity", params.id] }),
  });
  const summary = useMutation({
    mutationFn: () => api(`/api/v1/ai/summaries/opportunity/${params.id}`, { method: "POST" }),
  });
  const nba = useMutation({
    mutationFn: () => api(`/api/v1/opportunities/${params.id}/nba`, { method: "POST" }),
  });

  if (!can("opportunities.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState message="This opportunity is not in your tenant." />;
  const opp = query.data;
  const brief = summary.data?.data as { summary?: string; is_mock?: boolean } | undefined;
  const next = nba.data?.data as { action?: string; reason?: string } | undefined;

  return (
    <div>
      <PageHeader
        eyebrow="Deal room"
        title={opp.name}
        subtitle={`${labelize(opp.stage)} · ${money(opp.amount)} · ${opp.probability}%`}
        actions={
          <>
            {can("opportunities.write") ? (
              <Button
                variant="line"
                onClick={() => {
                  form.reset(opp);
                  setOpen(true);
                }}
              >
                Edit
              </Button>
            ) : null}
            {can("ai.copilot") ? (
              <Button variant="ghost" onClick={() => summary.mutate()}>
                Summarize
              </Button>
            ) : null}
            {can("opportunities.close") && opp.stage !== "closed_won" ? (
              <Button onClick={() => closeWon.mutate()}>Close won</Button>
            ) : null}
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Motion</p>
          <ul className="mt-4 space-y-3 text-sm">
            <li className="flex justify-between"><span className="text-[var(--muted)]">Stage</span><Badge tone="gold">{labelize(opp.stage)}</Badge></li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Amount</span>{money(opp.amount)}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Probability</span>{opp.probability}%</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Close</span>{opp.expected_close || "—"}</li>
          </ul>
          <p className="mt-5 text-sm leading-6 text-[var(--muted)]">Next step: {opp.next_step || "not set"}</p>
          <Link href={`/accounts/${opp.account_id}`} className="mt-4 inline-block text-sm text-brand">
            Open account 360
          </Link>
          <Button variant="line" className="mt-4 w-full" onClick={() => nba.mutate()}>
            Next best action
          </Button>
          {next?.action ? (
            <p className="mt-3 text-sm leading-6">
              {next.action}
              <span className="mt-1 block text-[var(--muted)]">{next.reason}</span>
            </p>
          ) : null}
        </div>
        <div className="panel p-5 xl:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm text-ink">Deal brief</p>
            {brief?.is_mock ? <Badge tone="gold">Mock provider</Badge> : null}
          </div>
          <p className="whitespace-pre-wrap text-sm leading-7 text-[var(--muted)]">
            {brief?.summary ?? "Summarize to ground a brief in tools and knowledge. Numbers stay in SQL."}
          </p>
        </div>
      </div>
      <div className="mt-8">
        <h2 className="mb-4 text-xl font-semibold text-navy">Ledger</h2>
        <Timeline entityType="opportunity" entityId={opp.id} />
      </div>
      <Drawer open={open} title="Edit opportunity" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => save.mutate(values))} className="space-y-4">
          <Field label="Name"><Input {...form.register("name", { required: true })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Stage">
              <Select {...form.register("stage")}>
                {OPP_STAGES.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
              </Select>
            </Field>
            <Field label="Amount"><Input {...form.register("amount")} /></Field>
          </div>
          <Field label="Expected close"><Input type="date" {...form.register("expected_close")} /></Field>
          <Field label="Next step"><Textarea rows={3} {...form.register("next_step")} /></Field>
          <FormActions pending={save.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
    </div>
  );
}
