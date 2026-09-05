"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, when } from "@/lib/format";
import type { IntelligenceSignal } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

export default function SignalsPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["signals"],
    queryFn: async () => (await api<IntelligenceSignal[]>("/api/v1/market/desk/signals")).data ?? [],
    enabled: can("signals.read"),
  });
  if (!can("signals.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message="Signals could not be assembled." />;
  const rows = query.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Evidence"
        title="Signals"
        subtitle="Every row stores source, evidence, confidence, and a recommended action. Mock providers stay labeled."
        actions={<Link href="/market" className="text-sm text-brand">Back to markets</Link>}
      />
      {rows.length === 0 ? (
        <EmptyState title="No signals" body="Refresh mock providers or wait for a live vendor. Empty stays empty." />
      ) : (
        <div className="space-y-3">
          {rows.map((row) => (
            <article key={row.id} className="panel p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-ink">{row.title}</p>
                <div className="flex gap-2">
                  <Badge>{labelize(row.kind)}</Badge>
                  <Badge tone={row.impact === "high" ? "rose" : "gold"}>{row.impact}</Badge>
                  {row.is_mock ? <Badge tone="gold">Mock</Badge> : null}
                </div>
              </div>
              <p className="mt-3 text-sm leading-6 text-[var(--muted)]">{row.evidence}</p>
              <p className="mt-2 text-xs text-[var(--muted)]">
                {row.source} · confidence {row.confidence} · {when(row.occurred_at)}
              </p>
              <p className="mt-2 text-sm">{row.recommended_action}</p>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
