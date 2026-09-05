"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, when } from "@/lib/format";
import type { TriggerEvent } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

export default function TriggersPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["triggers"],
    queryFn: async () => (await api<TriggerEvent[]>("/api/v1/market/desk/triggers")).data ?? [],
    enabled: can("signals.read"),
  });
  if (!can("signals.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message="Triggers could not be assembled." />;
  const rows = query.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Buying events"
        title="Triggers"
        subtitle="Hiring, RFP, news, and budget events. Confirm with a human before treating mock news as fact."
        actions={<Link href="/market" className="text-sm text-brand">Back to markets</Link>}
      />
      {rows.length === 0 ? (
        <EmptyState title="No triggers" body="A live news provider has not been connected. Seed or refresh to persist labeled mock events." />
      ) : (
        <div className="space-y-3">
          {rows.map((row) => (
            <article key={row.id} className="panel p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-ink">{row.title}</p>
                <div className="flex gap-2">
                  <Badge>{labelize(row.trigger_type)}</Badge>
                  {row.is_mock ? <Badge tone="gold">Mock</Badge> : null}
                </div>
              </div>
              <p className="mt-3 text-sm leading-6 text-[var(--muted)]">{row.body}</p>
              <p className="mt-2 text-xs text-[var(--muted)]">
                {row.source} · {when(row.occurred_at)} · confidence {row.confidence}
              </p>
              {row.account_id ? (
                <Link href={`/accounts/${row.account_id}`} className="mt-3 inline-block text-sm text-brand">
                  Open account
                </Link>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
