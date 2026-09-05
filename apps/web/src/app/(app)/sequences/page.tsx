"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Drawer, Field, FormActions, Select } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import type { Enrollment, Lead, Sequence } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

export default function SequencesPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<{ sequence_id: string; lead_id: string }>();
  const sequences = useQuery({
    queryKey: ["sequences"],
    queryFn: async () => (await api<Sequence[]>("/api/v1/lifecycle/sequences")).data ?? [],
    enabled: can("sequences.read"),
  });
  const enrollments = useQuery({
    queryKey: ["enrollments"],
    queryFn: async () => (await api<Enrollment[]>("/api/v1/lifecycle/enrollments")).data ?? [],
    enabled: can("sequences.read"),
  });
  const leads = useQuery({
    queryKey: ["leads"],
    queryFn: async () => (await api<Lead[]>("/api/v1/leads")).data ?? [],
    enabled: can("leads.read") && open,
  });
  const enroll = useMutation({
    mutationFn: (body: { sequence_id: string; lead_id: string }) =>
      api(`/api/v1/lifecycle/sequences/${body.sequence_id}/enroll`, { method: "POST", body: JSON.stringify({ lead_id: body.lead_id }) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["enrollments"] });
      void client.invalidateQueries({ queryKey: ["approvals"] });
      setOpen(false);
    },
  });

  if (!can("sequences.read")) return <DeniedState />;
  if (sequences.isLoading) return <LoadingState label="Reading sequences" />;
  if (sequences.isError) return <ErrorState message="Sequences could not be assembled." />;
  const rows = sequences.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Phase 10"
        title="Sequences"
        subtitle="Enroll drafts the first step into Approvals or a task. Nothing is sent from this desk."
        actions={can("sequences.write") ? <Button onClick={() => setOpen(true)}>Enroll lead</Button> : null}
      />
      {rows.length === 0 ? (
        <EmptyState title="No sequences" body="The SDR cadence is empty until someone authors steps." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "Sequence", cell: (row) => row.name },
            { key: "channel", header: "Channel", cell: (row) => labelize(row.channel) },
            { key: "status", header: "Status", cell: (row) => <Badge>{labelize(row.status)}</Badge> },
            { key: "purpose", header: "Purpose", cell: (row) => labelize(row.purpose) },
          ]}
        />
      )}
      <h2 className="mb-3 mt-8 text-xl font-semibold text-navy">Enrollments</h2>
      {(enrollments.data ?? []).length === 0 ? (
        <EmptyState title="No enrollments" body="Opt-out and missing email consent are refused." />
      ) : (
        <DataTable
          rows={enrollments.data ?? []}
          columns={[
            { key: "id", header: "Enrollment", cell: (row) => row.id.slice(0, 8) },
            { key: "status", header: "Status", cell: (row) => <Badge tone="ok">{labelize(row.status)}</Badge> },
            { key: "step", header: "Step", cell: (row) => String(row.current_step) },
          ]}
        />
      )}
      <Drawer open={open} title="Enroll a lead" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => enroll.mutate(values))} className="space-y-4">
          <Field label="Sequence">
            <Select {...form.register("sequence_id", { required: true })}>
              <option value="">Select</option>
              {rows.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </Select>
          </Field>
          <Field label="Lead">
            <Select {...form.register("lead_id", { required: true })}>
              <option value="">Select</option>
              {(leads.data ?? []).map((row) => (
                <option key={row.id} value={row.id}>{row.first_name} {row.last_name} · {row.company_name}</option>
              ))}
            </Select>
          </Field>
          <p className="text-xs text-[var(--muted)]">Send stays in Approvals. Live email is off.</p>
          <FormActions pending={enroll.isPending} onCancel={() => setOpen(false)} label="Enroll" />
        </form>
      </Drawer>
    </div>
  );
}
