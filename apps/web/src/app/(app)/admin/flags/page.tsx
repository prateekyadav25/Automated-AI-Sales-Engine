"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

type Flag = { id: string; key: string; enabled: boolean; description: string };

export default function FlagsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["flags"],
    queryFn: async () => (await api<Flag[]>("/api/v1/admin/flags")).data ?? [],
    enabled: can("flags.read"),
  });
  const toggle = useMutation({
    mutationFn: (flag: Flag) =>
      api(`/api/v1/admin/flags/${flag.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !flag.enabled }),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["flags"] }),
  });

  if (!can("flags.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message="Flags could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="House"
        title="Feature flags"
        subtitle="Unfinished engines stay off. No fake dashboards hide behind a switch."
      />
      {rows.length === 0 ? (
        <EmptyState title="No flags" body="Seed creates default autonomy flags." />
      ) : (
        <ul className="space-y-2">
          {rows.map((row) => (
            <li key={row.id} className="panel flex items-center justify-between gap-4 px-4 py-4">
              <div>
                <p className="text-sm text-ink">{row.key}</p>
                <p className="mt-1 text-xs text-[var(--muted)]">{row.description}</p>
              </div>
              <button
                disabled={!can("flags.write")}
                className="flex items-center gap-3"
                onClick={() => toggle.mutate(row)}
              >
                <Badge tone={row.enabled ? "ok" : "neutral"}>{row.enabled ? "On" : "Off"}</Badge>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
