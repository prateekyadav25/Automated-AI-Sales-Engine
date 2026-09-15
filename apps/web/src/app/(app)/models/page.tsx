"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { DatasetVersion, ModelCard, ModelVersion, Readiness } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";

export default function ModelsPage() {
  const { can } = useAuth();
  const cards = useQuery({
    queryKey: ["models"],
    queryFn: async () => (await api<ModelCard[]>("/api/v1/lifecycle/models")).data ?? [],
    enabled: can("revops.read"),
  });
  const readiness = useQuery({
    queryKey: ["ml-readiness"],
    queryFn: async () => (await api<Readiness[]>("/api/v1/ml/readiness")).data ?? [],
    enabled: can("ml.view"),
  });
  const datasets = useQuery({
    queryKey: ["ml-datasets"],
    queryFn: async () => (await api<DatasetVersion[]>("/api/v1/ml/datasets")).data ?? [],
    enabled: can("ml.view"),
  });
  const registry = useQuery({
    queryKey: ["ml-models"],
    queryFn: async () => (await api<ModelVersion[]>("/api/v1/ml/models")).data ?? [],
    enabled: can("ml.view"),
  });

  if (!can("revops.read")) return <DeniedState />;
  if (cards.isLoading) return <LoadingState label="Reading model cards" />;
  if (cards.isError) return <ErrorState message="Model cards could not be assembled." />;
  const rows = cards.data ?? [];
  const trained = (registry.data ?? []).filter((row) => row.is_rules !== 1 && row.algorithm !== "rules");
  const challenger = (registry.data ?? []).find((row) => row.status === "CHALLENGER");

  return (
    <div>
      <PageHeader
        eyebrow="Revenue intelligence"
        title="Model cards"
        subtitle="Production scoring stays on rules-v1/rules-v2. last_trained is null until a model is actually trained. No invented accuracy."
      />
      {rows.length === 0 ? (
        <EmptyState title="No cards" body="Rules-v1 cards appear when scoring engines are commissioned." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "Card", cell: (row) => row.name },
            { key: "purpose", header: "Purpose", cell: (row) => row.purpose },
            { key: "ver", header: "Version", cell: (row) => <Badge>{row.version}</Badge> },
            { key: "status", header: "Status", cell: (row) => row.status },
            { key: "trained", header: "Last trained", cell: (row) => row.last_trained ?? "null" },
            { key: "notes", header: "Notes", cell: (row) => row.notes },
          ]}
        />
      )}

      {can("ml.view") ? (
        <>
          <h2 className="mb-3 mt-10 text-xl font-semibold text-navy" data-testid="readiness-heading">
            Training readiness
          </h2>
          {readiness.isLoading ? (
            <LoadingState label="Reading readiness" />
          ) : readiness.isError ? (
            <ErrorState message="Readiness could not be assembled." />
          ) : (readiness.data ?? []).length === 0 ? (
            <EmptyState title="No tasks" body="Prediction tasks are seeded per tenant." />
          ) : (
            <DataTable
              rows={(readiness.data ?? []).map((row) => ({ ...row, id: row.task_key }))}
              columns={[
                { key: "task", header: "Task", cell: (row) => row.task_key },
                {
                  key: "status",
                  header: "Status",
                  cell: (row) => (
                    <span data-testid={`readiness-${row.task_key}`}>
                      <Badge>{row.recommended_status}</Badge>
                    </span>
                  ),
                },
                { key: "rows", header: "Samples", cell: (row) => String(row.rows) },
                { key: "pos", header: "Positive", cell: (row) => String(row.positive) },
                { key: "neg", header: "Negative", cell: (row) => String(row.negative) },
                { key: "pending", header: "Pending", cell: (row) => String(row.pending) },
                { key: "censored", header: "Censored", cell: (row) => String(row.censored) },
                { key: "history", header: "History days", cell: (row) => String(row.history_days) },
                {
                  key: "gate",
                  header: "Gate",
                  cell: (row) => (
                    <span data-testid={`readiness-gate-${row.task_key}`}>
                      {row.recommended_status === "READY_FOR_EXPERIMENT" ? "READY" : "NOT READY"}
                    </span>
                  ),
                },
                { key: "min", header: "Minimum needed", cell: (row) => `${row.minimum_rows} / ${row.minimum_positive} pos` },
                { key: "reason", header: "Note", cell: (row) => row.reason },
              ]}
            />
          )}

          <h2 className="mb-3 mt-10 text-xl font-semibold text-navy" data-testid="datasets-heading">
            Datasets
          </h2>
          {datasets.isLoading ? (
            <LoadingState label="Reading datasets" />
          ) : datasets.isError ? (
            <ErrorState message="Datasets could not be assembled." />
          ) : (datasets.data ?? []).length === 0 ? (
            <EmptyState title="No datasets" body="Build a point-in-time dataset only after snapshots exist. Empty is expected." />
          ) : (
            <DataTable
              rows={datasets.data ?? []}
              columns={[
                { key: "task", header: "Task", cell: (row) => row.task_key },
                { key: "ver", header: "Version", cell: (row) => row.version },
                { key: "rows", header: "Rows", cell: (row) => String(row.row_count) },
                { key: "pos", header: "Positive", cell: (row) => String(row.positive_count) },
                { key: "neg", header: "Negative", cell: (row) => String(row.negative_count) },
                { key: "cen", header: "Censored", cell: (row) => String(row.censored_count) },
                { key: "fp", header: "Fingerprint", cell: (row) => row.fingerprint.slice(0, 12) },
              ]}
            />
          )}

          <h2 className="mb-3 mt-10 text-xl font-semibold text-navy" data-testid="registry-heading">
            Model registry
          </h2>
          <p className="mb-3 text-sm text-slate" data-testid="shadow-indicator">
            Challenger: {challenger ? `${challenger.version} SHADOW` : "none"}
          </p>
          {registry.isLoading ? (
            <LoadingState label="Reading registry" />
          ) : registry.isError ? (
            <ErrorState message="Registry could not be assembled." />
          ) : trained.length === 0 ? (
            <EmptyState title="NO TRAINED MODEL" body="Rules remain CHAMPION. Experimental ML starts as SHADOW only after a readiness gate and a governed promotion." />
          ) : (
            <DataTable
              rows={trained}
              columns={[
                { key: "task", header: "Task", cell: (row) => row.task_key },
                { key: "ver", header: "Version", cell: (row) => row.version },
                { key: "status", header: "Status", cell: (row) => row.status },
                { key: "algo", header: "Algorithm", cell: (row) => row.algorithm },
                { key: "metrics", header: "Metrics", cell: (row) => row.metrics_json ?? "null" },
              ]}
            />
          )}
        </>
      ) : null}
    </div>
  );
}
