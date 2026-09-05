"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, when } from "@/lib/format";
import type { Task } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["task", params.id],
    queryFn: async () => (await api<Task>(`/api/v1/tasks/${params.id}`)).data,
    enabled: can("tasks.read"),
  });
  const toggle = useMutation({
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
    onSuccess: () => void client.invalidateQueries({ queryKey: ["task", params.id] }),
  });

  if (!can("tasks.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState message="This task is not in your tenant." />;
  const task = query.data;

  return (
    <div>
      <PageHeader
        eyebrow="Work"
        title={task.title}
        subtitle={`${labelize(task.source)} · ${labelize(task.priority)}`}
        actions={
          can("tasks.write") ? (
            <Button onClick={() => toggle.mutate(task)}>{task.status === "done" ? "Reopen" : "Complete"}</Button>
          ) : null
        }
      />
      <div className="panel max-w-2xl p-5">
        <ul className="space-y-3 text-sm">
          <li className="flex justify-between"><span className="text-[var(--muted)]">Status</span><Badge tone={task.status === "done" ? "ok" : "gold"}>{labelize(task.status)}</Badge></li>
          <li className="flex justify-between"><span className="text-[var(--muted)]">Due</span>{when(task.due_at)}</li>
          <li className="flex justify-between"><span className="text-[var(--muted)]">Linked</span>{task.entity_type ? `${task.entity_type} ${task.entity_id.slice(0, 8)}` : "—"}</li>
        </ul>
        <p className="mt-5 text-sm leading-6 text-[var(--muted)]">{task.description || "No description."}</p>
      </div>
    </div>
  );
}
