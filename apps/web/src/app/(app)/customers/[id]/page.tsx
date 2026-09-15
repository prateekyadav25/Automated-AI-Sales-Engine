"use client";

import { AutomationTrace } from "@/components/automation-trace";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Select } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize, money, when } from "@/lib/format";
import type { Customer360 } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

export default function Customer360Page() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const client = useQueryClient();
  const [churnReason, setChurnReason] = useState("adoption");
  const query = useQuery({
    queryKey: ["customer-360", params.id],
    queryFn: async () => (await api<Customer360>(`/api/v1/post-sale/customers/${params.id}`)).data,
    enabled: can("success.read"),
    refetchInterval: 5000,
  });
  const churn = useMutation({
    mutationFn: () =>
      api(`/api/v1/customers/${params.id}/churn`, {
        method: "POST",
        body: JSON.stringify({ reason: churnReason }),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["customer-360", params.id] }),
  });

  if (!can("success.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Opening the customer record" />;
  if (query.isError || !query.data) return <ErrorState message="This customer is not in your tenant." />;
  const row = query.data;
  const customer = row.customer;
  const openRisks = row.risks.filter((item) => item.status === "open");

  return (
    <div>
      <PageHeader
        eyebrow="Customer 360"
        title={row.account_name || customer.account_name || "Customer"}
        subtitle={`${labelize(row.lifecycle_state)} · ${money(customer.arr)} · health ${row.health_total ?? "—"} (${row.health_version})`}
        actions={
          can("success.write") && customer.status !== "churned" ? (
            <div className="flex gap-2">
              <Select value={churnReason} onChange={(event) => setChurnReason(event.target.value)} aria-label="Churn reason">
                {["adoption", "support", "price", "budget", "product_fit", "competitor", "strategy", "business_closure", "other"].map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
              <Button variant="line" data-testid="mark-churned" onClick={() => churn.mutate()}>
                Mark churned
              </Button>
            </div>
          ) : null
        }
      />
      <div className="mb-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-5">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Lifecycle</p>
          <p className="mt-2 text-lg font-semibold text-navy">{labelize(row.lifecycle_state)}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">Trend {labelize(row.health_trend)}</p>
        </div>
        <div className="panel p-5" data-testid="health-score">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Health</p>
          <p className="mt-2 text-lg font-semibold text-navy">{row.health_total ?? "—"}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            Evidence coverage {row.health_data_coverage ?? 0}% · {row.health_version}
          </p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            {row.unavailable_components ? `Unavailable: ${row.unavailable_components}` : "Evidence-only components"}
          </p>
        </div>
        <div className="panel p-5">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Renewal</p>
          <p className="mt-2 text-lg font-semibold text-navy">
            {row.renewal_countdown_days == null ? "—" : `${row.renewal_countdown_days} days`}
          </p>
          <p className="mt-1 text-xs text-[var(--muted)]">Readiness {row.renewal_readiness} · {when(row.renewal_date)}</p>
          {row.renewal_why_ready?.length ? <p className="mt-1 text-xs text-[var(--muted)]">Ready: {row.renewal_why_ready.join("; ")}</p> : null}
          {row.renewal_why_at_risk?.length ? <p className="mt-1 text-xs text-[var(--muted)]">At risk: {row.renewal_why_at_risk.join("; ")}</p> : null}
        </div>
        <div className="panel p-5">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Open risks</p>
          <p className="mt-2 text-lg font-semibold text-navy">{openRisks.length}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">{row.onboarding_status || "No onboarding status"}</p>
        </div>
      </div>
      <div className="mb-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {[
          { key: "usage", label: "Usage", state: row.usage_freshness || "MOCK", at: row.last_usage_at },
          { key: "support", label: "Support", state: row.support_freshness || "NOT_CONNECTED", at: row.last_support_at },
          { key: "finance", label: "Finance", state: row.finance_freshness || "NOT_CONNECTED", at: row.last_finance_at },
          { key: "commercial", label: "Commercial", state: row.commercial_freshness || "LIVE", at: null },
        ].map((card) => (
          <div key={card.key} className="panel p-5" data-testid={`freshness-${card.key}`}>
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">{card.label}</p>
            <p className="mt-2 text-lg font-semibold text-navy">{card.state === "NOT_CONNECTED" || card.state === "NOT_CONFIGURED" ? "NOT CONNECTED" : card.state}</p>
            <p className="mt-1 text-xs text-[var(--muted)]">{card.at ? `Last event ${when(card.at)}` : "No live event yet"}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <div data-testid="customer-automation">
          <AutomationTrace entityType="customer" entityId={customer.id} />
        </div>
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Contract</p>
          {row.contract ? (
            <ul className="mt-4 space-y-2 text-sm">
              <li className="flex justify-between gap-3"><span className="text-[var(--muted)]">Status</span><span>{labelize(row.contract.status)}</span></li>
              <li className="flex justify-between gap-3"><span className="text-[var(--muted)]">Value</span><span>{row.contract.total_value == null ? "Unknown" : money(row.contract.total_value)}</span></li>
              <li className="flex justify-between gap-3"><span className="text-[var(--muted)]">Term</span><span>{row.contract.term_months ?? "Unknown"}</span></li>
              <li className="flex justify-between gap-3"><span className="text-[var(--muted)]">Escalation</span><span>{row.contract.escalation_pct ?? "Unknown"}</span></li>
            </ul>
          ) : (
            <p className="mt-4 text-sm text-[var(--muted)]">No contract persisted.</p>
          )}
          {row.handoff ? (
            <p className="mt-4 text-sm text-[var(--muted)]">
              Handoff {labelize(row.handoff.status)}
              {row.handoff.missing_fields.length ? ` · missing ${row.handoff.missing_fields.join(", ")}` : ""}
            </p>
          ) : null}
        </div>
      </div>
      <div className="mt-6 grid gap-4 xl:grid-cols-2">
        <div className="panel p-5">
          <p className="text-sm font-semibold text-navy">Onboarding</p>
          {row.milestones.length === 0 ? (
            <EmptyState title="No milestones" body="Closed Won mints the default template." />
          ) : (
            <ul className="mt-4 space-y-2 text-sm">
              {row.milestones.map((item) => (
                <li key={item.id} className="flex justify-between gap-3">
                  <span>{item.title}</span>
                  <Badge tone={item.status === "blocked" ? "rose" : item.status === "done" || item.status === "completed" ? "ok" : "neutral"}>
                    {labelize(item.status)}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-4 text-xs text-[var(--muted)]">
            TTV kickoff {row.time_to_value.days_to_kickoff ?? "—"}d · go-live {row.time_to_value.days_to_go_live ?? "—"}d
          </p>
        </div>
        <div className="panel p-5">
          <p className="text-sm font-semibold text-navy">Risks</p>
          {row.risks.length === 0 ? (
            <p className="mt-4 text-sm text-[var(--muted)]">No persisted customer risks.</p>
          ) : (
            <ul className="mt-4 space-y-3 text-sm">
              {row.risks.map((item) => (
                <li key={item.id}>
                  <p className="font-medium">{labelize(item.risk_type)}</p>
                  <p className="text-xs text-[var(--muted)]">{item.summary}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="mt-6 grid gap-4 xl:grid-cols-2">
        <div className="panel p-5">
          <p className="text-sm font-semibold text-navy">Expansion</p>
          {row.expansion.length === 0 ? (
            <p className="mt-4 text-sm text-[var(--muted)]">No evidence-supported recommendations yet. Amount stays unknown.</p>
          ) : (
            <ul className="mt-4 space-y-3 text-sm">
              {row.expansion.map((item) => (
                <li key={item.id}>
                  <p className="font-medium">{item.title}</p>
                  <p className="text-xs text-[var(--muted)]">
                    {labelize(item.kind)} · confidence {item.confidence} · amount {item.amount ?? "null"}
                  </p>
                </li>
              ))}
            </ul>
          )}
          {row.usage ? (
            <p className="mt-4 text-xs text-[var(--muted)]">
              Usage {row.usage.provider} · {row.usage.is_mock ? "MOCK" : "live"} · {row.usage.evidence}
            </p>
          ) : null}
        </div>
        <div className="panel p-5">
          <p className="text-sm font-semibold text-navy">Advocacy</p>
          {row.advocacy.length === 0 ? (
            <p className="mt-4 text-sm text-[var(--muted)]">Not every healthy customer is an advocate.</p>
          ) : (
            <ul className="mt-4 space-y-3 text-sm">
              {row.advocacy.map((item) => (
                <li key={item.id}>
                  <p className="font-medium">{labelize(item.type)}</p>
                  <p className="text-xs text-[var(--muted)]">
                    Score {item.score} · quote {item.quote ?? "null"}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="mt-8">
        <h2 className="mb-4 text-xl font-semibold text-navy">Revenue timeline</h2>
        {row.timeline.length === 0 ? (
          <EmptyState title="No timeline yet" body="Closed Won, handoff, and Autopilot events land here." />
        ) : (
          <ol className="relative space-y-3 border-l border-[var(--line)] pl-5">
            {row.timeline.slice(-20).reverse().map((item, index) => (
              <li key={`${item.kind}-${item.title}-${index}`} className="panel relative p-4">
                <span className="absolute -left-[27px] top-5 h-2.5 w-2.5 rounded-full bg-brand" />
                <p className="text-sm font-medium text-ink">{item.title}</p>
                <p className="mt-1 text-[11px] uppercase tracking-wide text-[var(--muted)]">
                  {labelize(item.kind)} · {item.source || item.entity_type} · {when(item.occurred_at)}
                </p>
              </li>
            ))}
          </ol>
        )}
      </div>
      <p className="mt-6 text-sm">
        <Link href={`/accounts/${customer.account_id}`} className="text-brand">Open account</Link>
      </p>
    </div>
  );
}
