"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Field, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import type { Approval } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

export default function ApprovalsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [editId, setEditId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const query = useQuery({
    queryKey: ["approvals"],
    queryFn: async () => (await api<Approval[]>("/api/v1/ai/approvals")).data ?? [],
    enabled: can("ai.approvals.read"),
    refetchInterval: 5000,
  });
  const decide = useMutation({
    mutationFn: ({
      id,
      decision,
      note,
      body,
      pause,
    }: {
      id: string;
      decision: string;
      note?: string;
      body?: string;
      pause?: boolean;
    }) =>
      api(`/api/v1/ai/approvals/${id}/decide`, {
        method: "POST",
        body: JSON.stringify({
          decision,
          note: note || "Reviewed in Approval Center",
          payload_patch: body ? { body } : null,
          pause_entity: Boolean(pause),
        }),
      }),
    onSuccess: () => {
      setEditId(null);
      void client.invalidateQueries({ queryKey: ["approvals"] });
      void client.invalidateQueries({ queryKey: ["autonomy-status"] });
    },
  });

  if (!can("ai.approvals.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message="Approvals could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Your job"
        title="Approvals"
        subtitle="Authorize send, spend, and dial here. Evidence is on the card. You do not need the lead screen to decide."
      />
      {rows.length === 0 ? (
        <EmptyState title="Nothing in the chamber" body="Autopilot queues Level 2 actions when consent and policy allow." />
      ) : (
        <div className="space-y-3">
          {rows.map((row) => (
            <article key={row.id} className="panel space-y-3 p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-sm text-ink">{row.title}</p>
                  <p className="mt-1 text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
                    L{row.action_level} · {labelize(row.action_type)}
                  </p>
                </div>
                <Badge tone={row.status === "pending" ? "gold" : row.status === "approved" ? "ok" : "rose"}>
                  {labelize(row.status)}
                </Badge>
              </div>
              <dl className="grid gap-2 text-sm md:grid-cols-2">
                <div><dt className="text-[var(--muted)]">Who</dt><dd>{row.who || row.entity_id || "—"}</dd></div>
                <div><dt className="text-[var(--muted)]">Why</dt><dd>{row.why || "—"}</dd></div>
                <div><dt className="text-[var(--muted)]">Evidence</dt><dd>{row.evidence || "—"}</dd></div>
                <div><dt className="text-[var(--muted)]">Risk</dt><dd>{row.risk || "—"}</dd></div>
                <div className="md:col-span-2"><dt className="text-[var(--muted)]">Expected outcome</dt><dd>{row.expected_outcome || "—"}</dd></div>
                {row.budget_impact ? <div><dt className="text-[var(--muted)]">Budget</dt><dd>{row.budget_impact}</dd></div> : null}
              </dl>
              {row.message ? <p className="whitespace-pre-wrap rounded-lg bg-azure-50/60 p-3 text-sm text-ink">{row.message}</p> : null}
              {row.decision_note ? <p className="text-xs text-[var(--muted)]">{row.decision_note}</p> : null}
              {row.entity_type === "lead" && row.entity_id ? (
                <Link href={`/leads/${row.entity_id}`} className="text-sm text-brand">Inspect lead</Link>
              ) : null}
              {can("ai.approvals.decide") && row.status === "pending" ? (
                <div className="flex flex-wrap items-center gap-3">
                  <Button onClick={() => decide.mutate({ id: row.id, decision: "approve" })}>Approve</Button>
                  <Button
                    variant="line"
                    onClick={() => {
                      setEditId(row.id);
                      setDraft(row.message || "");
                    }}
                  >
                    Edit & Approve
                  </Button>
                  <Button variant="line" onClick={() => decide.mutate({ id: row.id, decision: "reject" })}>
                    Reject
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => decide.mutate({ id: row.id, decision: "reject", note: "Paused automation", pause: true })}
                  >
                    Pause automation
                  </Button>
                </div>
              ) : null}
              {editId === row.id ? (
                <form
                  className="space-y-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    decide.mutate({ id: row.id, decision: "approve", body: draft, note: "Edited and approved" });
                  }}
                >
                  <Field label="Message">
                    <Textarea rows={5} value={draft} onChange={(event) => setDraft(event.target.value)} />
                  </Field>
                  <div className="flex gap-2">
                    <Button type="submit">Save and approve</Button>
                    <Button type="button" variant="ghost" onClick={() => setEditId(null)}>
                      Cancel
                    </Button>
                  </div>
                </form>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
