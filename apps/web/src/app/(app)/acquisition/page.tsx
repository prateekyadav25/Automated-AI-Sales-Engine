"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, CheckField, Drawer, Field, FormActions, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, when } from "@/lib/format";
import type { DedupeReview, InboundCapture } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type Overview = { captures: number; accepted: number; duplicate_review: number; pending_dedupe: number };

type CaptureForm = {
  first_name: string;
  last_name: string;
  email: string;
  company_name: string;
  title: string;
  source: string;
  channel: string;
  campaign: string;
  utm_source: string;
  utm_medium: string;
  landing_page: string;
  consent_email: boolean;
};

export default function AcquisitionPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const form = useForm<CaptureForm>({
    defaultValues: {
      first_name: "",
      last_name: "",
      email: "",
      company_name: "",
      title: "",
      source: "inbound",
      channel: "website",
      campaign: "",
      utm_source: "",
      utm_medium: "",
      landing_page: "",
      consent_email: false,
    },
  });
  const overview = useQuery({
    queryKey: ["acquisition-overview"],
    queryFn: async () => (await api<Overview>("/api/v1/acquisition/overview")).data,
    enabled: can("acquisition.read"),
  });
  const captures = useQuery({
    queryKey: ["captures"],
    queryFn: async () => (await api<InboundCapture[]>("/api/v1/acquisition/captures")).data ?? [],
    enabled: can("acquisition.read"),
  });
  const reviews = useQuery({
    queryKey: ["dedupe"],
    queryFn: async () => (await api<DedupeReview[]>("/api/v1/acquisition/dedupe?status=pending")).data ?? [],
    enabled: can("acquisition.read"),
  });
  const capture = useMutation({
    mutationFn: (body: CaptureForm) =>
      api("/api/v1/acquisition/capture", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (res) => {
      void client.invalidateQueries({ queryKey: ["captures"] });
      void client.invalidateQueries({ queryKey: ["dedupe"] });
      void client.invalidateQueries({ queryKey: ["acquisition-overview"] });
      void client.invalidateQueries({ queryKey: ["leads"] });
      setOpen(false);
      form.reset();
      const reviewsOpened = (res.data as { reviews_opened?: number } | null)?.reviews_opened ?? 0;
      setNotice(reviewsOpened ? `Capture stored. ${reviewsOpened} review(s) opened.` : "Capture stored and scored.");
    },
    onError: () => setNotice("Capture was declined. Check opt-out and permissions."),
  });
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: string }) =>
      api(`/api/v1/acquisition/dedupe/${id}/decide`, { method: "POST", body: JSON.stringify({ decision }) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["dedupe"] }),
  });

  if (!can("acquisition.read")) return <DeniedState />;
  if (captures.isLoading || overview.isLoading) return <LoadingState label="Reading inbound" />;
  if (captures.isError || overview.isError) return <ErrorState message="Acquisition could not be assembled." />;
  const rows = captures.data ?? [];
  const queue = reviews.data ?? [];
  const k = overview.data;

  return (
    <div>
      <PageHeader
        eyebrow="Phase 8"
        title="Acquisition"
        subtitle="Inbound capture stores source, channel, campaign, and consent. Uncertain matches wait for review. Sequences stay off."
        actions={
          can("acquisition.capture") ? <Button onClick={() => setOpen(true)}>Record inbound</Button> : null
        }
      />
      {notice ? <p className="mb-4 text-sm text-brand">{notice}</p> : null}
      {k ? (
        <div className="mb-6 grid gap-4 md:grid-cols-4">
          {[
            ["Captures", k.captures],
            ["Accepted", k.accepted],
            ["Duplicate review", k.duplicate_review],
            ["Pending dedupe", k.pending_dedupe],
          ].map(([label, value]) => (
            <div key={String(label)} className="panel p-5">
              <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">{label}</p>
              <p className="mt-3 text-3xl font-semibold text-navy">{value}</p>
            </div>
          ))}
        </div>
      ) : null}
      <h2 className="mb-3 text-xl font-semibold text-navy">Dedupe review</h2>
      {queue.length === 0 ? (
        <EmptyState title="No uncertain matches" body="Exact email duplicates and fuzzy company names land here." />
      ) : (
        <div className="mb-8 space-y-3">
          {queue.map((row) => (
            <article key={row.id} className="panel flex flex-wrap items-center justify-between gap-4 p-5">
              <div>
                <p className="text-sm">{row.reason}</p>
                <p className="mt-1 text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
                  {labelize(row.match_kind)} · {row.confidence}
                </p>
              </div>
              {can("acquisition.write") ? (
                <div className="flex gap-2">
                  <Button onClick={() => decide.mutate({ id: row.id, decision: "merge" })}>Merge</Button>
                  <Button variant="line" onClick={() => decide.mutate({ id: row.id, decision: "dismiss" })}>
                    Dismiss
                  </Button>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      )}
      <h2 className="mb-3 text-xl font-semibold text-navy">Inbound captures</h2>
      {rows.length === 0 ? (
        <EmptyState title="No inbound yet" body="Record a capture. Paid ads and sequences are not live." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "email", header: "Email", cell: (row) => row.email },
            { key: "company", header: "Company", cell: (row) => row.company_name || "—" },
            { key: "channel", header: "Channel", cell: (row) => row.channel || "—" },
            { key: "status", header: "Status", cell: (row) => <Badge tone={row.status === "accepted" ? "ok" : "gold"}>{labelize(row.status)}</Badge> },
            { key: "consent", header: "Consent", cell: (row) => (row.consent_email ? "email ok" : "none") },
            { key: "when", header: "When", cell: (row) => when(row.captured_at) },
          ]}
        />
      )}
      <Drawer open={open} title="Record inbound" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => capture.mutate(values))} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name"><Input {...form.register("first_name", { required: true })} /></Field>
            <Field label="Last name"><Input {...form.register("last_name", { required: true })} /></Field>
          </div>
          <Field label="Email"><Input type="email" {...form.register("email", { required: true })} /></Field>
          <Field label="Company"><Input {...form.register("company_name")} /></Field>
          <Field label="Title"><Input {...form.register("title")} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Channel"><Input {...form.register("channel")} /></Field>
            <Field label="Campaign"><Input {...form.register("campaign")} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="UTM source"><Input {...form.register("utm_source")} /></Field>
            <Field label="UTM medium"><Input {...form.register("utm_medium")} /></Field>
          </div>
          <Field label="Landing page"><Input {...form.register("landing_page")} /></Field>
          <CheckField label="Email consent" {...form.register("consent_email")} />
          <FormActions pending={capture.isPending} onCancel={() => setOpen(false)} label="Capture and score" />
        </form>
      </Drawer>
    </div>
  );
}
