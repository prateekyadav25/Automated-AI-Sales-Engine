"use client";

import { DataTable } from "@/components/data-table";
import { ListToolbar } from "@/components/list-toolbar";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Drawer, Field, FormActions, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { TASK_PRIORITIES, TASK_STATUSES } from "@/lib/constants";
import { labelize, when } from "@/lib/format";
import { qs, useDebounced } from "@/lib/hooks";
import type { Task } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type TaskForm = {
  title: string;
  description: string;
  status: string;
  priority: string;
  due_at: string;
  entity_type: string;
  entity_id: string;
};

export default function TasksPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const search = useDebounced(q);
  const form = useForm<TaskForm>({
    defaultValues: { title: "", description: "", status: "open", priority: "medium", due_at: "", entity_type: "", entity_id: "" },
  });

  const query = useQuery({
    queryKey: ["tasks", search, status, page],
    queryFn: () => api<Task[]>(`/api/v1/tasks${qs({ q: search, status, page, page_size: 25 })}`),
    enabled: can("tasks.read"),
  });
  const create = useMutation({
    mutationFn: (body: TaskForm) =>
      api("/api/v1/tasks", {
        method: "POST",
        body: JSON.stringify({ ...body, due_at: body.due_at || null }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
      setOpen(false);
      form.reset();
    },
  });
  const complete = useMutation({
    mutationFn: (row: Task) =>
      api(`/api/v1/tasks/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: row.title,
          description: row.description,
          status: row.status === "done" ? "open" : "done",
          priority: row.priority,
          due_at: row.due_at,
          entity_type: row.entity_type,
          entity_id: row.entity_id,
          source: row.source,
        }),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["tasks"] }),
  });

  if (!can("tasks.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading the work queue" />;
  if (query.isError) return <ErrorState message="Work could not be assembled." />;
  const rows = query.data?.data ?? [];
  const total = query.data?.meta?.total ?? rows.length;

  return (
    <div>
      <PageHeader
        eyebrow="Work queue"
        title="Tasks"
        subtitle="Human, workflow, and AI-created work share one desk. Closing a deal creates a success handoff."
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
        filterOptions={[{ value: "", label: "All statuses" }, ...TASK_STATUSES.map((item) => ({ value: item, label: labelize(item) }))]}
        onCreate={can("tasks.write") ? () => setOpen(true) : undefined}
        createLabel="Create work"
      />
      {rows.length === 0 ? (
        <EmptyState title="The queue is clear" body="Create work, or close a deal to mint a success handoff." />
      ) : (
        <>
          <DataTable
            rows={rows}
            columns={[
              { key: "title", header: "Work", cell: (row) => row.title },
              { key: "status", header: "Status", cell: (row) => <Badge tone={row.status === "done" ? "ok" : "gold"}>{labelize(row.status)}</Badge> },
              { key: "priority", header: "Priority", cell: (row) => labelize(row.priority) },
              { key: "source", header: "Source", cell: (row) => labelize(row.source) },
              { key: "due", header: "Due", cell: (row) => when(row.due_at) },
              {
                key: "act",
                header: "",
                cell: (row) =>
                  can("tasks.write") ? (
                    <button
                      className="text-brand"
                      onClick={(event) => {
                        event.stopPropagation();
                        complete.mutate(row);
                      }}
                    >
                      {row.status === "done" ? "Reopen" : "Complete"}
                    </button>
                  ) : null,
              },
            ]}
          />
          <Pagination page={page} pageSize={25} total={total} onPage={setPage} />
        </>
      )}
      <Drawer open={open} title="Create work" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <Field label="Title"><Input {...form.register("title", { required: true })} /></Field>
          <Field label="Description"><Textarea rows={4} {...form.register("description")} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Status">
              <Select {...form.register("status")}>
                {TASK_STATUSES.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
              </Select>
            </Field>
            <Field label="Priority">
              <Select {...form.register("priority")}>
                {TASK_PRIORITIES.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
              </Select>
            </Field>
          </div>
          <Field label="Due"><Input type="datetime-local" {...form.register("due_at")} /></Field>
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} label="Create task" />
        </form>
      </Drawer>
    </div>
  );
}
