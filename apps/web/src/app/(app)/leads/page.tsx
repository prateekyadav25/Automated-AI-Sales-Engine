"use client";

import { DataTable } from "@/components/data-table";
import { ListToolbar } from "@/components/list-toolbar";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, CheckField, Drawer, Field, FormActions, Input, Score, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { LEAD_STATUSES } from "@/lib/constants";
import { fullName, labelize } from "@/lib/format";
import { qs, useDebounced } from "@/lib/hooks";
import type { DiscoveryRun, Lead } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type LeadForm = {
  first_name: string;
  last_name: string;
  email: string;
  company_name: string;
  title: string;
  status: string;
  source: string;
  channel: string;
  notes: string;
  intent_score: number;
  engagement_score: number;
  has_buying_trigger: boolean;
  consent_email: boolean;
};

export default function LeadsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const search = useDebounced(q);
  const form = useForm<LeadForm>({
    defaultValues: {
      first_name: "",
      last_name: "",
      email: "",
      company_name: "",
      title: "",
      status: "new",
      source: "human",
      channel: "",
      notes: "",
      intent_score: 0,
      engagement_score: 0,
      has_buying_trigger: false,
      consent_email: false,
    },
  });

  const query = useQuery({
    queryKey: ["leads", search, status, page],
    queryFn: () => api<Lead[]>(`/api/v1/leads${qs({ q: search, status, page, page_size: 25 })}`),
    enabled: can("leads.read"),
  });

  const create = useMutation({
    mutationFn: (body: LeadForm) =>
      api("/api/v1/leads", { method: "POST", body: JSON.stringify({ ...body, source: "human" }) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["leads"] });
      setOpen(false);
      form.reset();
    },
  });
  const discover = useMutation({
    mutationFn: () => api<DiscoveryRun>("/api/v1/discovery/run", { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["leads"] });
    },
  });

  if (!can("leads.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading inbound" />;
  if (query.isError) return <ErrorState message="Leads could not be assembled." />;

  const rows = query.data?.data ?? [];
  const total = query.data?.meta?.total ?? rows.length;

  return (
    <div>
      <PageHeader
        eyebrow="Step 2 · Start here"
        title="Leads"
        subtitle="Autopilot discovers when enabled and a live provider returns people. Run discovery now is only for acceleration. New lead is for someone you found yourself."
      />
      <ListToolbar
        query={q}
        onQuery={(value) => {
          setQ(value);
          setPage(1);
        }}
        filter={status}
        onFilter={(value) => {
          setStatus(value);
          setPage(1);
        }}
        filterOptions={[{ value: "", label: "All statuses" }, ...LEAD_STATUSES.map((item) => ({ value: item, label: labelize(item) }))]}
        onCreate={can("leads.write") ? () => setOpen(true) : undefined}
        createLabel="New lead"
        extra={
          can("leads.write") ? (
            <Button variant="line" onClick={() => discover.mutate()} disabled={discover.isPending}>
              {discover.isPending ? "Discovering…" : "Run discovery now"}
            </Button>
          ) : undefined
        }
      />
      {discover.isError ? (
        <p className="mb-3 text-sm text-[#e08b7a]">Discovery could not run. No invented people were stored.</p>
      ) : null}
      {discover.data?.data ? (
        <p className="mb-3 text-sm text-[var(--muted)]">
          {discover.data.data.is_mock ? "Labeled mock. " : ""}
          Created {discover.data.data.created} from {discover.data.data.candidate_count} vendor rows.
          {discover.data.data.reason ? ` ${discover.data.data.reason}` : ""}
        </p>
      ) : null}
      {rows.length === 0 ? (
        <EmptyState
          title="No inbound yet"
          body="Create a lead or import a CSV. Empty stays empty."
          action={can("leads.write") ? <button className="text-brand" onClick={() => setOpen(true)}>Create the first lead</button> : undefined}
        />
      ) : (
        <>
          <DataTable
            rows={rows}
            href={(row) => `/leads/${row.id}`}
            columns={[
              { key: "name", header: "Name", cell: (row) => fullName(row.first_name, row.last_name) },
              { key: "company", header: "Company", cell: (row) => row.company_name || "—" },
              { key: "title", header: "Title", cell: (row) => row.title || "—" },
              {
                key: "source",
                header: "Source",
                cell: (row) => {
                  const source = row.source === "manual" ? "human" : row.source;
                  const tone = source === "ai_discovery" ? "blue" : source === "import" ? "gold" : "neutral";
                  const label =
                    source === "ai_discovery" ? "Discovered" : source === "import" ? "Import" : source === "human" ? "Human" : labelize(source);
                  return <Badge tone={tone}>{label}</Badge>;
                },
              },
              {
                key: "status",
                header: "Status",
                cell: (row) => <Badge>{labelize(row.status)}</Badge>,
              },
              { key: "score", header: "Score", cell: (row) => <Score value={row.latest_score?.total} /> },
            ]}
          />
          <Pagination page={page} pageSize={25} total={total} onPage={setPage} />
        </>
      )}
      <Drawer open={open} title="Open a lead" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name"><Input {...form.register("first_name", { required: true })} /></Field>
            <Field label="Last name"><Input {...form.register("last_name", { required: true })} /></Field>
          </div>
          <Field label="Email"><Input type="email" {...form.register("email")} /></Field>
          <Field label="Company"><Input {...form.register("company_name")} /></Field>
          <Field label="Title"><Input {...form.register("title")} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Status">
              <Select {...form.register("status")}>
                {LEAD_STATUSES.map((item) => (
                  <option key={item} value={item}>{labelize(item)}</option>
                ))}
              </Select>
            </Field>
            <Field label="Source"><Input value="human" disabled /></Field>
          </div>
          <Field label="Notes"><Textarea rows={4} {...form.register("notes")} /></Field>
          <CheckField label="Has buying trigger" {...form.register("has_buying_trigger")} />
          <CheckField label="Email consent" {...form.register("consent_email")} />
          {create.isError ? <p className="text-sm text-[#e08b7a]">The lead could not be opened.</p> : null}
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} label="Create lead" />
        </form>
      </Drawer>
    </div>
  );
}
