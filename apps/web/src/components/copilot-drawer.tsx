"use client";

import { api } from "@agrayian/sdk";
import { useEffect, useState } from "react";
import { Button, Textarea } from "@/components/ui";

export function CopilotDrawer({
  open,
  seed,
  onClose,
}: {
  open: boolean;
  seed?: string;
  onClose: () => void;
}) {
  const [message, setMessage] = useState(seed || "Which accounts deserve attention today?");
  const [reply, setReply] = useState("");
  const [meta, setMeta] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (seed) setMessage(seed);
  }, [seed]);

  if (!open) return null;

  async function ask() {
    setPending(true);
    try {
      const res = await api<{ reply: string; is_mock: boolean; provider: string }>("/api/v1/ai/copilot/chat", {
        method: "POST",
        body: JSON.stringify({ message }),
      });
      setReply(res.data?.reply ?? "");
      setMeta(`${res.data?.provider ?? ""}${res.data?.is_mock ? " · mock" : ""}`);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-navy/20 backdrop-blur-sm">
      <button className="flex-1" onClick={onClose} aria-label="Close copilot" />
      <aside className="glass-strong flex h-full w-full max-w-xl flex-col border-l">
        <div className="border-b border-[var(--line)] px-6 py-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">Intelligence</p>
          <h2 className="text-xl font-semibold text-navy">Copilot</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">Uses approved tools only. It does not invent pipeline numbers.</p>
        </div>
        <div className="flex-1 overflow-auto px-6 py-5">
          {reply ? (
            <div className="panel p-4">
              <p className="text-[11px] uppercase tracking-wide text-[var(--muted)]">{meta}</p>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-ink">{reply}</p>
            </div>
          ) : (
            <p className="text-sm text-[var(--muted)]">Ask for research, deal risk, or a draft. Send stays in Approvals.</p>
          )}
        </div>
        <div className="space-y-3 border-t border-[var(--line)] p-6">
          <Textarea rows={4} value={message} onChange={(e) => setMessage(e.target.value)} />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Dismiss
            </Button>
            <Button disabled={pending} onClick={() => void ask()}>
              {pending ? "Thinking" : "Ask"}
            </Button>
          </div>
        </div>
      </aside>
    </div>
  );
}
