"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState } from "@/components/states";
import { Badge, Button, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { ChatResponse } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { FormEvent, useState } from "react";

type Turn = { role: "human" | "machine"; text: string; meta?: string; citations?: ChatResponse["citations"] };

export default function IntelligencePage() {
  const { can } = useAuth();
  const [message, setMessage] = useState("Which accounts deserve research this week?");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  if (!can("ai.copilot")) return <DeniedState />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const asked = message.trim();
    if (!asked) return;
    setPending(true);
    setError("");
    setTurns((current) => [...current, { role: "human", text: asked }]);
    try {
      const res = await api<ChatResponse>("/api/v1/ai/copilot/chat", {
        method: "POST",
        body: JSON.stringify({ message: asked }),
      });
      setTurns((current) => [
        ...current,
        {
          role: "machine",
          text: res.data?.reply ?? "No reply.",
          meta: `${res.data?.provider ?? "unknown"}${res.data?.is_mock ? " · mock" : ""}`,
          citations: res.data?.citations,
        },
      ]);
      setMessage("");
    } catch {
      setError("The copilot could not complete that turn.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Intelligence"
        title="Copilot"
        subtitle="Tools, then services, then authorization, then the database. The model never writes SQL."
      />
      <div className="grid gap-4 xl:grid-cols-[1.4fr_0.8fr]">
        <div className="panel flex min-h-[560px] flex-col">
          <div className="flex-1 space-y-4 overflow-auto p-5">
            {turns.length === 0 ? (
              <p className="text-sm text-[var(--muted)]">
                Ask for research, risk, or a draft. Pipeline numbers stay in SQL.
              </p>
            ) : (
              turns.map((turn, index) => (
                <div key={`${turn.role}-${index}`} className={turn.role === "human" ? "text-right" : ""}>
                  <div className={`inline-block max-w-[85%] rounded-2xl px-4 py-3 text-left text-sm leading-6 ${turn.role === "human" ? "bg-brand-50 text-ink" : "bg-slate-50"}`}>
                    {turn.meta ? <p className="mb-2 text-[11px] uppercase tracking-[0.16em] text-[var(--muted)]">{turn.meta}</p> : null}
                    <p className="whitespace-pre-wrap">{turn.text}</p>
                    {turn.citations?.length ? (
                      <ul className="mt-3 space-y-1 text-xs text-[var(--muted)]">
                        {turn.citations.map((cite, citeIndex) => (
                          <li key={`${cite.title}-${citeIndex}`}>{cite.title}: {cite.text.slice(0, 160)}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </div>
              ))
            )}
          </div>
          <form onSubmit={onSubmit} className="space-y-3 border-t border-[var(--line)] p-5">
            <Textarea rows={3} value={message} onChange={(event) => setMessage(event.target.value)} />
            {error ? <p className="text-sm text-[#e08b7a]">{error}</p> : null}
            <div className="flex justify-end">
              <Button disabled={pending}>{pending ? "Thinking" : "Ask"}</Button>
            </div>
          </form>
        </div>
        <aside className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-brand">Guardrails</p>
          <ul className="mt-4 space-y-4 text-sm leading-6 text-[var(--muted)]">
            <li>Scores and KPIs are computed in SQL. The model may only explain them.</li>
            <li>Email send queues the Approval Center. There is no live send without a provider.</li>
            <li>Answers without a citation must abstain rather than invent a playbook.</li>
          </ul>
          <div className="mt-8"><Badge tone="gold">Tool-grounded</Badge></div>
        </aside>
      </div>
    </div>
  );
}
