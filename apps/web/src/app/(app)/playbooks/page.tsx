"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Drawer, Field, FormActions, Select } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import type { Account, Playbook, WorkflowRun } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

export default function PlaybooksPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<{ playbook_id: string; entity_id: string }>();
  const playbooks = useQuery({
    queryKey: ["playbooks"],
    queryFn: async () => (await api<Playbook[]>("/api/v1/lifecycle/playbooks")).data ?? [],
    enabled: can("revops.read"),
  });
  const runs = useQuery({
    queryKey: ["playbook-runs"],
    queryFn: async () => (await api<WorkflowRun[]>("/api/v1/lifecycle/playbooks/runs")).data ?? [],
    enabled: can("revops.read"),
  });
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: async () => (await api<Account[]>("/api/v1/accounts")).data ?? [],
    enabled: can("accounts.read") && open,
  });
  const run = useMutation({
    mutationFn: (body: { playbook_id: string; entity_id: string }) =>
      api(`/api/v1/lifecycle/playbooks/${body.playbook_id}/run`, {
        method: "POST",
        body: JSON.stringify({ entity_type: "account", entity_id: body.entity_id }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["playbook-runs"] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
      setOpen(false);
    },
  });

  if (!can("revops.read")) return <DeniedState />;
  if (playbooks.isLoading) return <LoadingState label="Reading playbooks" />;
  if (playbooks.isError) return <ErrorState message="RevOps could not be assembled." />;
  const rows = playbooks.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Phase 22"
        title="Playbooks"
        subtitle="Runs persist. Allowed actions: create task, write activity, request approval. No live send."
        actions={can("revops.write") ? <Button onClick={() => setOpen(true)}>Run playbook</Button> : null}
      />
      {rows.length === 0 ? (
        <EmptyState title="No playbooks" body="Autonomy stays at task and approval level until a human authors one." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "Playbook", cell: (row) => row.name },
            { key: "trigger", header: "Trigger", cell: (row) => row.trigger_event },
            { key: "auto", header: "Autonomy", cell: (row) => String(row.autonomy_level) },
            { key: "on", header: "Active", cell: (row) => <Badge tone={row.is_active ? "ok" : "gold"}>{row.is_active ? "on" : "off"}</Badge> },
          ]}
        />
      )}
      <h2 className="mb-3 mt-8 text-xl font-semibold text-navy">Runs</h2>
      {(runs.data ?? []).length === 0 ? (
        <EmptyState title="No runs" body="A playbook is not real until a run is stored." />
      ) : (
        <DataTable
          rows={runs.data ?? []}
          columns={[
            { key: "trigger", header: "Trigger", cell: (row) => row.trigger_event },
            { key: "status", header: "Status", cell: (row) => <Badge tone="ok">{labelize(row.status)}</Badge> },
            { key: "log", header: "Log", cell: (row) => row.log_json },
          ]}
        />
      )}
      <Drawer open={open} title="Run playbook" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => run.mutate(values))} className="space-y-4">
          <Field label="Playbook">
            <Select {...form.register("playbook_id", { required: true })}>
              <option value="">Select</option>
              {rows.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </Select>
          </Field>
          <Field label="Account">
            <Select {...form.register("entity_id", { required: true })}>
              <option value="">Select</option>
              {(accounts.data ?? []).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </Select>
          </Field>
          <FormActions pending={run.isPending} onCancel={() => setOpen(false)} label="Run" />
        </form>
      </Drawer>
    </div>
  );
}
