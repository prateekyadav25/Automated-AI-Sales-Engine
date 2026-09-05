"use client";

import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { labelize, when } from "@/lib/format";
import type { Activity } from "@/lib/types";

export function Timeline({ entityType, entityId }: { entityType: string; entityId: string }) {
  const query = useQuery({
    queryKey: ["activities", entityType, entityId],
    queryFn: async () =>
      (await api<Activity[]>(`/api/v1/activities?entity_type=${entityType}&entity_id=${entityId}`)).data ?? [],
  });
  if (query.isLoading) return <LoadingState label="Loading activity" />;
  if (query.isError) return <ErrorState message="The timeline could not be loaded." />;
  const rows = query.data ?? [];
  if (rows.length === 0) {
    return <EmptyState title="No activity yet" body="Human and machine actions will appear here as they happen." />;
  }
  return (
    <ol className="relative space-y-3 border-l border-[var(--line)] pl-5">
      {rows.map((row) => (
        <li key={row.id} className="panel relative p-4">
          <span className="absolute -left-[27px] top-5 h-2.5 w-2.5 rounded-full bg-brand" />
          <div className="flex items-start justify-between gap-4">
            <p className="text-sm font-medium text-ink">{row.title}</p>
            <p className="shrink-0 text-[11px] text-[var(--muted)]">{when(row.created_at)}</p>
          </div>
          <p className="mt-1 text-[11px] uppercase tracking-wide text-[var(--muted)]">
            {labelize(row.activity_type)} · {labelize(row.actor_type)}
          </p>
          {row.body ? <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{row.body}</p> : null}
        </li>
      ))}
    </ol>
  );
}
