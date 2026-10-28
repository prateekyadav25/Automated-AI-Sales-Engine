"use client";

import { Line } from "@/components/ds";
import type { CommercialClose } from "@/lib/types";
import Link from "next/link";

function recorded(value: string | null | undefined, empty = "Not recorded") {
  const text = (value || "").trim();
  return text || empty;
}

export function CommercialClosePanel({ view }: { view: CommercialClose }) {
  const state = view.activated ? "Active" : view.won ? "Won" : view.quote_status === "accepted" ? "Accepted" : view.quote_status || "Open";
  const amount = view.currency ? `${view.currency} ${view.total}` : `${view.total} (currency not recorded)`;
  return (
    <section className="panel" data-testid="commercial-close">
      <header className="panel-head">
        <h2>Commercial decision</h2>
        <span>{state}</span>
      </header>
      <div className="panel-body">
        <Line label="State" value={state} />
        <Line label="Product" value={recorded(view.customer_facing_name)} />
        <Line label="Offer" value={recorded(view.offer_label)} />
        <Line label="SKU" value={recorded(view.sku)} />
        <Line label="Quote" value={view.quote_id ? `Version ${view.quote_version ?? "—"} · ${view.quote_status}` : "Not recorded"} />
        <Line label="Quoted amount" value={view.quote_id ? amount : "Not recorded"} />
        <Line label="Discount" value={view.discount_pct == null ? "Not recorded" : `${view.discount_pct}%`} />
        <Line label="Tax" value={view.tax_pct == null ? "Not recorded" : `${view.tax_pct}%`} />
        <Line label="Scope" value={recorded(view.scope_text)} />
        <Line label="Terms" value={recorded(view.terms)} />
        <Line label="Billing cadence" value={recorded(view.billing_cadence)} />
        <Line label="Service dates" value={view.service_start || view.service_end ? `${view.service_start || "Not recorded"} to ${view.service_end || "Not recorded"}` : "Not recorded"} />
        <Line label="Acceptance" value={view.acceptance_source ? `${view.acceptance_source} · ${view.acceptance_review || "not reviewed"}` : "Not recorded"} />
        <Line label="Relationship" value={recorded(view.acceptance_relationship)} />
        <Line label="Evidence" value={recorded(view.acceptance_evidence)} />
        <Line label="Provider verified" value={view.provider_verified ? "Yes" : "No"} />
        <Line label="Payment" value={view.payment_status ? view.payment_status : "Not recorded"} />
        <Line label="Onboarding" value={recorded(view.onboarding_status, "Not opened")} />
        {view.checklist?.length ? (
          <div data-testid="purchase-checklist">
            {view.checklist.map((item) => (
              <Line key={item.id} label={item.title} value={`${item.status}${item.next_action ? ` · ${item.next_action}` : ""}`} />
            ))}
          </div>
        ) : null}
        <Line label="Owner" value={recorded(view.owner_name)} />
        <Line label="Next action" value={recorded(view.onboarding_next_action)} />
        <Line label="Onboarding blocker" value={recorded(view.onboarding_blocker, "None recorded")} />
        <Line label="Fixture" value={view.fixture ? "Yes" : "No"} />
        {view.blockers.length ? (
          <div data-testid="commercial-blockers">
            {view.blockers.map((item) => (
              <p key={item} className="tag bad">{item}</p>
            ))}
          </div>
        ) : null}
        {view.missing_information.length ? (
          <p className="small muted">Missing: {view.missing_information.join(", ")}</p>
        ) : null}
        {view.external_block ? <p className="small muted">{view.external_block}</p> : null}
        <p className="small muted">{view.note}</p>
        <div className="ds-flex" style={{ marginTop: 16 }}>
          {view.quote_id ? <Link href={`/commercial/quotes/${view.quote_id}`}>Open quote</Link> : null}
          {view.customer_id ? <Link href={`/customers/${view.customer_id}`}>Open customer</Link> : null}
          <Link href={`/opportunities/${view.opportunity_id}`}>Open opportunity</Link>
        </div>
      </div>
    </section>
  );
}
