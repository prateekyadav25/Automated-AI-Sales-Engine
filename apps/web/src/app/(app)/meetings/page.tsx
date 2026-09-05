"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Drawer, Field, FormActions, Input, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { Meeting } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type Form = { title: string; summary: string; next_steps: string };
type ExtractForm = { title: string; transcript: string };

export default function MeetingsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [extractOpen, setExtractOpen] = useState(false);
  const form = useForm<Form>({ defaultValues: { title: "", summary: "", next_steps: "" } });
  const extractForm = useForm<ExtractForm>({ defaultValues: { title: "Extracted meeting notes", transcript: "" } });
  const query = useQuery({
    queryKey: ["meetings"],
    queryFn: async () => (await api<Meeting[]>("/api/v1/lifecycle/meetings")).data ?? [],
    enabled: can("meetings.read"),
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

  if (!can("meetings.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading meetings" />;
  if (query.isError) return <ErrorState message="Meetings could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Phase 12"
        title="Meetings"
        subtitle="Human notes, or extract key points from a pasted transcript. The model cites or abstains. Humans still own the close meeting."
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
            { key: "title", header: "Title", cell: (row) => row.title },
            { key: "summary", header: "Summary", cell: (row) => row.summary || "—" },
            { key: "next", header: "Next steps", cell: (row) => row.next_steps || "—" },
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
    </div>
  );
}
