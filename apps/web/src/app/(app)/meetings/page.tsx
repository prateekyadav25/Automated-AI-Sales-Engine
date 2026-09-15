"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Drawer, Field, FormActions, Input, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { Meeting } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type Form = { title: string; summary: string; next_steps: string };
type ExtractForm = { title: string; transcript: string };
type CaptureForm = { meeting_url: string };
type TranscriptForm = { transcript: string };

function insights(row: Meeting): { summary?: string; commitments?: string[]; objections?: string[]; risks?: string[]; next_actions?: string[]; abstained?: boolean } {
  try {
    return JSON.parse(row.insights_json || "{}");
  } catch {
    return {};
  }
}

export default function MeetingsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [extractOpen, setExtractOpen] = useState(false);
  const [selected, setSelected] = useState<Meeting | null>(null);
  const form = useForm<Form>({ defaultValues: { title: "", summary: "", next_steps: "" } });
  const extractForm = useForm<ExtractForm>({ defaultValues: { title: "Extracted meeting notes", transcript: "" } });
  const captureForm = useForm<CaptureForm>({ defaultValues: { meeting_url: "" } });
  const transcriptForm = useForm<TranscriptForm>({ defaultValues: { transcript: "" } });
  const query = useQuery({
    queryKey: ["meetings"],
    queryFn: async () => (await api<Meeting[]>("/api/v1/lifecycle/meetings")).data ?? [],
    enabled: can("meetings.read"),
    refetchInterval: 5000,
  });
  const create = useMutation({
    mutationFn: (body: Form) => api("/api/v1/lifecycle/meetings", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["meetings"] });
      setOpen(false);
      form.reset();
    },
  });
  const extract = useMutation({
    mutationFn: (body: ExtractForm) =>
      api("/api/v1/lifecycle/meetings/extract", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["meetings"] });
      setExtractOpen(false);
      extractForm.reset();
    },
  });
  const consent = useMutation({
    mutationFn: (id: string) => api(`/api/v1/lifecycle/meetings/${id}/consent`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["meetings"] });
      void client.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
  const capture = useMutation({
    mutationFn: ({ id, meeting_url }: { id: string; meeting_url: string }) =>
      api(`/api/v1/lifecycle/meetings/${id}/capture`, { method: "POST", body: JSON.stringify({ meeting_url }) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["meetings"] }),
  });
  const paste = useMutation({
    mutationFn: ({ id, transcript }: { id: string; transcript: string }) =>
      api(`/api/v1/lifecycle/meetings/${id}/transcript`, { method: "POST", body: JSON.stringify({ transcript }) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["meetings"] });
      transcriptForm.reset();
    },
  });

  if (!can("meetings.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading meetings" />;
  if (query.isError) return <ErrorState message="Meetings could not be assembled." />;
  const rows = query.data ?? [];
  const selectedInsights = selected ? insights(selected) : {};

  return (
    <div>
      <PageHeader
        eyebrow="Phase 12"
        title="Meetings"
        subtitle="Bot capture is consent-gated. Insights come from the transcript only. Manual paste stays available if Recall is not live."
        actions={
          can("meetings.write") ? (
            <div className="flex gap-2">
              <Button variant="line" onClick={() => setExtractOpen(true)}>Extract notes</Button>
              <Button onClick={() => setOpen(true)}>Log meeting</Button>
            </div>
          ) : null
        }
      />
      {rows.length === 0 ? (
        <EmptyState title="No meetings" body="Log a recap. The model does not invent attendees." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "title", header: "Title", cell: (row) => <button type="button" className="text-left text-navy underline" onClick={() => setSelected(row)}>{row.title}</button> },
            { key: "status", header: "Status", cell: (row) => row.status || "logged" },
            { key: "consent", header: "Record", cell: (row) => row.recording_consent ? <Badge>Consented</Badge> : "—" },
            { key: "capture", header: "Bot", cell: (row) => row.captures?.[0]?.status || "—" },
            { key: "when", header: "When", cell: (row) => row.start_at ? new Date(row.start_at).toLocaleString() : "—" },
            { key: "provider", header: "Provider", cell: (row) => row.is_mock ? "Mock" : (row.provider || "human") },
            { key: "summary", header: "Summary", cell: (row) => row.summary || "—" },
          ]}
        />
      )}
      <Drawer open={open} title="Log meeting" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <Field label="Title"><Input {...form.register("title", { required: true })} /></Field>
          <Field label="Summary"><Textarea rows={4} {...form.register("summary")} /></Field>
          <Field label="Next steps"><Textarea rows={3} {...form.register("next_steps")} /></Field>
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
      <Drawer open={extractOpen} title="Extract notes from a transcript" onClose={() => setExtractOpen(false)}>
        <form onSubmit={extractForm.handleSubmit((values) => extract.mutate(values))} className="space-y-4">
          <Field label="Title"><Input {...extractForm.register("title", { required: true })} /></Field>
          <Field label="Transcript"><Textarea rows={8} {...extractForm.register("transcript", { required: true })} /></Field>
          {extract.isError ? <p className="text-sm text-[#e08b7a]">Notes could not be extracted.</p> : null}
          <FormActions pending={extract.isPending} onCancel={() => setExtractOpen(false)} label="Extract" />
        </form>
      </Drawer>
      <Drawer open={Boolean(selected)} title={selected?.title || "Meeting"} onClose={() => setSelected(null)}>
        {selected ? (
          <div className="space-y-4">
            <p className="text-sm text-[var(--muted)]">{selected.summary || "No summary yet."}</p>
            <p className="text-xs uppercase tracking-[0.16em] text-brand">{selected.recording_consent ? "Recording consent recorded" : "Recording consent missing"}</p>
            {selected.transcript ? <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-xs">{selected.transcript}</pre> : null}
            <div>
              <p className="text-sm font-semibold text-navy">Insights</p>
              <p className="mt-1 text-sm">{selectedInsights.summary || "Insufficient transcript evidence."}</p>
              <p className="mt-2 text-xs text-[var(--muted)]">Commitments: {(selectedInsights.commitments || []).join("; ") || "—"}</p>
              <p className="text-xs text-[var(--muted)]">Objections: {(selectedInsights.objections || []).join("; ") || "—"}</p>
              <p className="text-xs text-[var(--muted)]">Risks: {(selectedInsights.risks || []).join("; ") || "—"}</p>
              <p className="text-xs text-[var(--muted)]">Next actions: {(selectedInsights.next_actions || []).join("; ") || "—"}</p>
            </div>
            {can("meetings.write") ? (
              <>
                {!selected.recording_consent ? (
                  <Button variant="line" onClick={() => consent.mutate(selected.id)} disabled={consent.isPending}>
                    Queue recording consent
                  </Button>
                ) : null}
                <form onSubmit={captureForm.handleSubmit((values) => capture.mutate({ id: selected.id, meeting_url: values.meeting_url }))} className="space-y-3">
                  <Field label="Meeting URL"><Input {...captureForm.register("meeting_url", { required: true })} /></Field>
                  <Button type="submit" variant="line" disabled={capture.isPending}>Schedule bot</Button>
                </form>
                <form onSubmit={transcriptForm.handleSubmit((values) => paste.mutate({ id: selected.id, transcript: values.transcript }))} className="space-y-3">
                  <Field label="Manual transcript fallback"><Textarea rows={5} {...transcriptForm.register("transcript", { required: true })} /></Field>
                  <FormActions pending={paste.isPending} onCancel={() => setSelected(null)} label="Save transcript" />
                </form>
              </>
            ) : null}
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
