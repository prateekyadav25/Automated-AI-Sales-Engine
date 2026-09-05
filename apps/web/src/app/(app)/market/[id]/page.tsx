"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Score } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import type { Market } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";

const SCORE_FIELDS: Array<[keyof Market, string]> = [
  ["attractiveness", "Attractiveness"],
  ["ai_readiness", "AI readiness"],
  ["technology_readiness", "Technology"],
  ["budget_potential", "Budget potential"],
  ["growth_potential", "Growth"],
  ["competitive_intensity", "Competition"],
  ["procurement_probability", "Procurement"],
  ["buying_timing", "Buying timing"],
];

export default function MarketDetailPage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["market", params.id],
    queryFn: async () => (await api<Market>(`/api/v1/market/${params.id}`)).data,
    enabled: can("markets.read"),
  });
  const score = useMutation({
    mutationFn: () => api(`/api/v1/market/${params.id}/score`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["market", params.id] }),
  });

  if (!can("markets.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState message="This market is not in your tenant." />;
  const market = query.data;

  return (
    <div>
      <PageHeader
        eyebrow="Market thesis"
        title={market.name}
        subtitle={`${labelize(market.industry)} · ${market.geography || "no geography"} · ${market.score_version}`}
        actions={
          can("markets.write") ? (
            <Button onClick={() => score.mutate()}>{score.isPending ? "Scoring…" : "Recalculate"}</Button>
          ) : null
        }
      />
      <div className="grid gap-4 xl:grid-cols-4">
        {SCORE_FIELDS.map(([key, label]) => (
          <div key={key} className="panel p-5">
            <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">{label}</p>
            <div className="mt-3 flex items-end justify-between">
              <p className="text-3xl font-semibold text-navy">{market[key] as number}</p>
              <Score value={market[key] as number} />
            </div>
          </div>
        ))}
      </div>
      <div className="panel mt-4 p-5">
        <Badge tone="gold">Deterministic</Badge>
        <p className="mt-3 text-sm leading-7 text-[var(--muted)]">{market.score_reasons || "Score to persist reasons."}</p>
        <p className="mt-4 text-sm leading-6">{market.description || "No narrative yet."}</p>
      </div>
    </div>
  );
}
