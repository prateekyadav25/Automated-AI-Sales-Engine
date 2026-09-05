"use client";

import { api } from "@agrayian/sdk";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type { SearchHit } from "@/lib/types";

const ROUTES = [
  { href: "/", label: "Home" },
  { href: "/automation/runs", label: "Autopilot" },
  { href: "/automation/approvals", label: "Approvals" },
  { href: "/leads", label: "Leads" },
  { href: "/accounts", label: "Accounts" },
  { href: "/contacts", label: "Contacts" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/customers", label: "Customers" },
  { href: "/tasks", label: "Tasks" },
  { href: "/imports", label: "Import" },
  { href: "/icps", label: "Who we sell to" },
  { href: "/market", label: "Market" },
  { href: "/market/signals", label: "Signals" },
  { href: "/acquisition", label: "Acquisition" },
  { href: "/campaigns", label: "Campaigns" },
  { href: "/sequences", label: "Sequences" },
  { href: "/conversations", label: "Conversations" },
  { href: "/meetings", label: "Meetings" },
  { href: "/deals", label: "Deals" },
  { href: "/commercial", label: "Commercial" },
  { href: "/forecast", label: "Forecast" },
  { href: "/success", label: "Success" },
  { href: "/renewals", label: "Renewals" },
  { href: "/expansion", label: "Expansion" },
  { href: "/advocacy", label: "Advocacy" },
  { href: "/playbooks", label: "Playbooks" },
  { href: "/models", label: "Models" },
  { href: "/admin/teams", label: "Teams" },
  { href: "/intelligence", label: "Copilot" },
  { href: "/knowledge", label: "Knowledge" },
];

const ENTITY_PATH: Record<string, string> = {
  account: "/accounts",
  lead: "/leads",
  contact: "/contacts",
  opportunity: "/opportunities",
  task: "/tasks",
  market: "/market",
  campaign: "/campaigns",
  sequence: "/sequences",
  product: "/commercial",
};

export function CommandPalette({
  open,
  onClose,
  onAsk,
}: {
  open: boolean;
  onClose: () => void;
  onAsk: (q: string) => void;
}) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || q.trim().length < 2) {
      setHits([]);
      return;
    }
    const handle = setTimeout(() => {
      void api<{ hits: SearchHit[] }>(`/api/v1/search?q=${encodeURIComponent(q)}`)
        .then((res) => setHits(res.data?.hits ?? []))
        .catch(() => setHits([]));
    }, 180);
    return () => clearTimeout(handle);
  }, [q, open]);

  const pages = useMemo(
    () => ROUTES.filter((item) => item.label.toLowerCase().includes(q.toLowerCase()) || !q),
    [q],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-navy/25 px-4 pt-[12vh] backdrop-blur-sm">
      <div className="glass-strong w-full max-w-2xl overflow-hidden rounded-2xl">
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search accounts, leads, deals…"
          className="w-full border-b border-[var(--line)] bg-transparent px-5 py-4 text-sm outline-none"
        />
        <div className="max-h-80 overflow-auto p-2">
          {pages.map((item) => (
            <button
              key={item.href}
              className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-azure-50/80"
              onClick={() => {
                router.push(item.href);
                onClose();
              }}
            >
              {item.label}
            </button>
          ))}
          {hits.map((hit) => (
            <button
              key={`${hit.entity_type}-${hit.id}`}
              className="flex w-full flex-col rounded-lg px-3 py-2 text-left hover:bg-azure-50/80"
              onClick={() => {
                router.push(`${ENTITY_PATH[hit.entity_type]}/${hit.id}`);
                onClose();
              }}
            >
              <span className="text-sm">{hit.title}</span>
              <span className="text-[11px] uppercase tracking-wide text-[var(--muted)]">
                {hit.entity_type} · {hit.subtitle}
              </span>
            </button>
          ))}
          {q ? (
            <button
              className="mt-1 flex w-full rounded-lg px-3 py-2 text-left text-sm text-brand hover:bg-brand-50"
              onClick={() => {
                onAsk(q);
                onClose();
              }}
            >
              Ask copilot: {q}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
