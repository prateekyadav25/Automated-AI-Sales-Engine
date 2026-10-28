"use client";

import { Checks, Go, Line, Notice, Panel } from "@/components/ds";
import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { Timeline } from "@/components/timeline";
import { Badge, Button, Drawer, Field, FormActions, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { OPP_STAGES } from "@/lib/constants";
import { labelize, recordedAmount } from "@/lib/format";
import { CommercialClosePanel } from "@/components/commercial-close";
import type { CommercialClose, Opportunity } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

const LOSS_REASONS = [
  "pricing",
  "competition",
  "timing",
  "budget",
  "product_fit",
  "relationship",
  "procurement",
  "legal",
  "no_decision",
  "other",
];

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
  const commercial = useQuery({
    queryKey: ["opportunity-commercial", params.id],
    queryFn: async () => (await api<CommercialClose>(`/api/v1/opportunities/${params.id}/commercial`)).data,
    enabled: can("opportunities.read"),
  });
  const closeWon = useMutation({
    mutationFn: () =>
      api(`/api/v1/opportunities/${params.id}/close-won`, {
        method: "POST",
        body: JSON.stringify({ quote_id: commercial.data?.quote_id, note: "Operator decision" }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["opportunity", params.id] });
      void client.invalidateQueries({ queryKey: ["opportunity-commercial", params.id] });
    },
  });
  const closeLost = useMutation({
    mutationFn: (reason: string) =>
      api(`/api/v1/opportunities/${params.id}/close-lost`, {
        method: "POST",
        body: JSON.stringify({ reason, note: "" }),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["opportunity", params.id] }),
  });
  const [lossReason, setLossReason] = useState("pricing");
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
        subtitle={`${labelize(opp.stage)} · Pipeline ${recordedAmount(opp.amount, "")} · ${opp.probability}%`}
        nextHref="/deals"
        nextLabel="Deal risk"
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
            {can("opportunities.close") && opp.stage !== "closed_won" && opp.stage !== "closed_lost" ? (
              <>
                <Button onClick={() => closeWon.mutate()} disabled={!commercial.data?.ready || closeWon.isPending}>
                  Close won
                </Button>
                <Select value={lossReason} onChange={(event) => setLossReason(event.target.value)} aria-label="Loss reason">
                  {LOSS_REASONS.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </Select>
                <Button variant="line" data-testid="close-lost" onClick={() => closeLost.mutate(lossReason)}>
                  Close lost
                </Button>
              </>
            ) : null}
          </>
        }
      />
      <Notice
        title="Next expected outcome: approved proposal"
        body="Commercial authorization and delivery readiness must precede acceptance. Approval is not delivery."
      />
      <div className="phase-nav">
        {["Qualification", "Discovery", "Solution", "Proposal", "Negotiation", "Won"].map((phase) => {
          const current =
            opp.stage === "closed_won"
              ? "Won"
              : commercial.data?.quote_status === "accepted"
                ? "Negotiation"
              : opp.stage === "discovery" || opp.stage === "demo"
                ? "Discovery"
                : opp.stage === "proposal"
                  ? "Proposal"
                  : opp.stage === "negotiation"
                    ? "Negotiation"
                    : "Qualification";
          return (
            <span key={phase} className={phase === current ? "active" : ""}>
              {phase}
            </span>
          );
        })}
      </div>
      {closeWon.isError ? <p className="tag bad">{(closeWon.error as Error).message}</p> : null}
      {commercial.data ? <CommercialClosePanel view={commercial.data} /> : null}
      <div className="ds-grid wide">
        <Panel title={opp.name}>
          <div className="between">
            <div>
              <div className="upper">{labelize(opp.stage)}</div>
              <div className="stat-label">Pipeline amount</div>
              <div className="stat-value num" data-testid="pipeline-amount">{recordedAmount(opp.amount, "")}</div>
              <div className="small muted">{opp.probability}% stage probability · before a new discount</div>
            </div>
            <Badge tone="blue">{labelize(opp.stage)}</Badge>
          </div>
          <Line label="Expected close" value={opp.expected_close || "Not recorded"} />
          <Line label="Next agreed step" value={opp.next_step || "Not recorded"} />
          <Line label="Forecast category" value="Derived from stage, not a separate forecast write" />
          <div className="ds-flex" style={{ marginTop: 20 }}>
            <Go href="/commercial/proposal" primary>Proposal</Go>
            <Go href="/commercial">Quote</Go>
            <Go href="/meetings">Meeting evidence</Go>
          </div>
        </Panel>
        <Panel title="Stage evidence and decisions">
          <Checks
            items={[
              { label: "Amount recorded", ok: Number(opp.amount) > 0 },
              { label: "Next step recorded", ok: Boolean(opp.next_step) },
              { label: "Expected close recorded", ok: Boolean(opp.expected_close) },
              { label: "Delivery owner confirms commitments", ok: false },
            ]}
          />
          <div style={{ marginTop: 16 }}>
            <Go href="/commercial">Review quote terms</Go>
          </div>
        </Panel>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Motion</p>
          <ul className="mt-4 space-y-3 text-sm">
            <li className="flex justify-between"><span className="text-[var(--muted)]">Stage</span><Badge tone="gold">{labelize(opp.stage)}</Badge></li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Pipeline amount</span>{recordedAmount(opp.amount, "")}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Probability</span>{opp.probability}%</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Close</span>{opp.expected_close || "—"}</li>
            {opp.loss_reason ? <li className="flex justify-between"><span className="text-[var(--muted)]">Lost</span>{opp.loss_reason}</li> : null}
          </ul>
          <p className="mt-5 text-sm leading-6 text-[var(--muted)]">Next step: {opp.next_step || "not set"}</p>
          <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
            Moving into proposal needs recorded qualification or meeting evidence. A missing fact blocks the stage instead of inventing progress.
          </p>
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
                {OPP_STAGES.filter((item) => item !== "closed_won" || opp.stage === "closed_won").map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
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
