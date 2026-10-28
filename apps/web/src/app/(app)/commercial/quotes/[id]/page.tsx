"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { StatusPill } from "@/components/workspace-ui";
import { useAuth } from "@/lib/auth";
import type { CommercialClose, Quote } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

function tone(status: string): "success" | "review" | "info" | "neutral" {
  if (status === "accepted") return "success";
  if (status === "approved") return "info";
  if (status === "sent") return "review";
  return "neutral";
}

export default function QuotePage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["quote", params.id],
    queryFn: async () => (await api<Quote>(`/api/v1/lifecycle/quotes/${params.id}`)).data,
    enabled: can("commercial.read"),
  });
  const commercial = useQuery({
    queryKey: ["opportunity-commercial", query.data?.opportunity_id],
    queryFn: async () => (await api<CommercialClose>(`/api/v1/opportunities/${query.data?.opportunity_id}/commercial`)).data,
    enabled: can("opportunities.read") && Boolean(query.data?.opportunity_id),
  });
  const accept = useMutation({
    mutationFn: () => api(`/api/v1/workflow/quotes/${params.id}/accept`, { method: "POST", body: JSON.stringify({ note: "" }) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["quote", params.id] }),
  });
  if (!can("commercial.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Opening the quote" />;
  if (query.isError || !query.data) return <ErrorState message="This quote is not in the tenant." />;
  const quote = query.data;
  return (
    <div>
      <PageHeader
        eyebrow="Commercial"
        title={`Quote ${quote.id.slice(0, 8)}`}
        subtitle="An issued or accepted version stays unchanged. Editing it creates a new draft. Acceptance is not close-won."
        nextHref="/commercial/proposal"
        nextLabel="Proposal"
        actions={
          can("commercial.write") && quote.status === "approved" ? (
            <Button onClick={() => accept.mutate()} disabled={accept.isPending}>Accept</Button>
          ) : null
        }
      />
      <div className={quote.status === "approved" || quote.status === "accepted" ? "callout good" : "callout warn"}>
        <div>
          <strong>{quote.status === "approved" || quote.status === "accepted" ? "Authorization recorded" : "Commercial authorization required"}</strong>
          <p>Approval and delivery are tracked separately. Editing material terms invalidates the authorization.</p>
        </div>
      </div>
      {accept.isError ? <p className="tag bad">{(accept.error as Error).message}</p> : null}
      <div className="ds-grid wide">
        <section className="panel">
          <header className="panel-head">
            <h2>Customer-facing quote</h2>
            <StatusPill tone={tone(quote.status)}>{quote.status}</StatusPill>
          </header>
          <div className="panel-body">
            <div className="quote-paper">
              <div className="between">
                <strong>AGRAYIAN AI LABS</strong>
                <span>{quote.id.slice(0, 8)}</span>
              </div>
              <hr className="rule" />
              <h2>Quote</h2>
              <p className="muted" style={{ marginTop: 10 }}>Prepared for this tenant opportunity.</p>
              <div style={{ marginTop: 20 }}>
                <div className="line-item"><span>Product</span><span>{quote.customer_facing_name || "Not recorded"}</span></div>
                <div className="line-item"><span>Offer</span><span>{quote.offer_label || "Not recorded"}</span></div>
                <div className="line-item"><span>SKU</span><span>{quote.sku || "Not recorded"}</span></div>
                <div className="line-item"><span>Version</span><span>{quote.version ?? "—"}</span></div>
                <div className="line-item"><span>Scope</span><span>{quote.scope_text || "Not recorded"}</span></div>
                <div className="line-item"><span>Subtotal</span><span className="num">{quote.currency ? `${quote.currency} ${quote.subtotal}` : quote.subtotal}</span></div>
                <div className="line-item"><span>Discount</span><span className="num">{quote.discount_pct ? `${quote.discount_pct}%` : "Not recorded"}</span></div>
                <div className="line-item"><span>Tax</span><span className="num">{quote.tax_pct ? `${quote.tax_pct}%` : "Not recorded"}</span></div>
                <div className="line-item"><span>Total</span><span className="num">{quote.currency ? `${quote.currency} ${quote.total}` : quote.total}</span></div>
              </div>
              <p className="small muted" style={{ marginTop: 22 }}>This version stays as quoted. A later catalogue edit does not change it. Acceptance is not close-won.</p>
            </div>
          </div>
        </section>
        <section className="panel">
          <header className="panel-head"><h2>Decision and delivery</h2></header>
          <div className="panel-body">
            <div className="line-item"><span>Authorization</span><span>{quote.status}</span></div>
            <div className="line-item"><span>Approval required</span><span>{quote.approval_required ? "Yes" : "No"}</span></div>
            <div className="line-item"><span>Delivery</span><span>Separate from approval</span></div>
            <div className="line-item"><span>Acceptance</span><span>{commercial.data?.quote_id === quote.id ? commercial.data.acceptance_source || "Not recorded" : "See this version"}</span></div>
            <div className="line-item"><span>Close-won</span><span>{commercial.data?.won && commercial.data.quote_id === quote.id ? "Won" : "Not won"}</span></div>
            <div className="line-item"><span>Payment</span><span>{commercial.data?.payment_status || "Not recorded"}</span></div>
            <p className="small" style={{ marginTop: 16 }}><Link href={`/opportunities/${quote.opportunity_id}`}>Open opportunity</Link></p>
          </div>
        </section>
      </div>
    </div>
  );
}
