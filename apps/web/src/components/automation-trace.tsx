"use client";

import { Badge } from "@/components/ui";
import { labelize } from "@/lib/format";
import type { EntityAutomation } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

export function AutomationTrace({ entityType, entityId }: { entityType: string; entityId: string }) {
  const query = useQuery({
    queryKey: ["automation-trace", entityType, entityId],
    queryFn: async () =>
      (await api<EntityAutomation>(`/api/v1/autonomy/entities/${entityType}/${entityId}`)).data,
    refetchInterval: 5000,
  });
  const row = query.data;
  if (!row || row.state === "NONE") {
    return (
      <div className="panel p-5">
        <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Automation</p>
        <p className="mt-3 text-sm text-[var(--muted)]">No Autopilot state yet. Enable Autopilot or wait for the next event.</p>
      </div>
    );
  }
  return (
    <div className="panel p-5">
      <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Automation</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge tone={row.paused || row.state === "BLOCKED" ? "rose" : row.state === "OUTREACH_APPROVAL_PENDING" ? "gold" : "ok"}>
          {labelize(row.state)}
        </Badge>
        {row.paused ? <Badge tone="rose">Paused</Badge> : null}
      </div>
      <ul className="mt-4 space-y-2 text-sm">
        <li className="flex justify-between gap-3"><span className="text-[var(--muted)]">Last action</span><span>{row.last_action || "—"}</span></li>
        <li className="flex justify-between gap-3"><span className="text-[var(--muted)]">Next</span><span>{row.next_action || "—"}</span></li>
        <li className="flex justify-between gap-3"><span className="text-[var(--muted)]">Blocked</span><span>{row.blocked_reason || "—"}</span></li>
        <li className="flex justify-between gap-3"><span className="text-[var(--muted)]">Workflow</span><span>{row.workflow || "—"}</span></li>
        <li className="flex justify-between gap-3"><span className="text-[var(--muted)]">Run</span><span>{row.run_status || "—"}</span></li>
      </ul>
      {row.run_id ? (
        <Link href="/automation/runs" className="mt-4 inline-block text-sm text-brand">
          Open Autopilot
        </Link>
      ) : null}
    </div>
  );
}
