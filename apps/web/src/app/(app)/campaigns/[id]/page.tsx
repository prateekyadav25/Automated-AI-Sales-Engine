"use client";

import { Checks, Go, Line, Panel, Stats } from "@/components/ds";
import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { StatusPill } from "@/components/workspace-ui";
import { useAuth } from "@/lib/auth";
import { labelize, money } from "@/lib/format";
import type { Campaign } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";

export default function CampaignWorkspacePage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["campaign", params.id],
    queryFn: async () => (await api<Campaign>(`/api/v1/lifecycle/campaigns/${params.id}`)).data,
    enabled: can("campaigns.read"),
  });
  if (!can("campaigns.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Opening the campaign" />;
  if (query.isError || !query.data) return <ErrorState message="This campaign is not in the tenant." />;
  const row = query.data;
  const spendRecorded = Boolean(row.last_synced_at);
  const previewIsRemote = (row.asset_ref || "").startsWith("https://") && !(row.asset_ref || "").includes("localhost");
  return (
    <div>
      <PageHeader
        eyebrow="Marketing"
        title={row.name}
        subtitle={`${labelize(row.channel)} · ${row.objective || "No objective recorded"}`}
        nextHref="/content"
        nextLabel="Content studio"
      />
      <Stats
        items={[
          { name: "Proposed budget", value: `${row.currency || ""} ${money(row.budget)}`.trim(), note: "Not authorization to spend" },
          { name: "Recorded spend", value: spendRecorded ? money(row.spent) : "Not recorded", note: "No paid ledger has been read" },
          { name: "Impressions", value: spendRecorded ? String(row.impressions ?? 0) : "Not read back", note: "Paid metrics are a separate check" },
          { name: "Activation", value: row.activated || row.status === "launched" ? row.status : "Not activated", note: row.assembly_status || "No assembly" },
        ]}
      />
      <div className="ds-grid wide">
        <Panel title="Campaign plan">
          <Line label="Product" value={row.offer_label || "No frozen product context"} />
          <Line label="Objective" value={row.objective || "Not recorded"} />
          <Line label="Audience" value={row.audience || "Not recorded"} />
          <Line label="Geography" value={row.geography || "Not recorded"} />
          <Line label="Dates" value={row.schedule_label || "Not recorded"} />
          <Line label="Destination" value={row.destination_url || row.destination || "Not recorded"} />
          <Line label="Activation" value="Not activated" />
          <hr className="rule" />
          <h3>Creative</h3>
          <p>{row.headline || "No headline"}</p>
          <p>{row.body || "No copy"}</p>
          <p>{row.call_to_action || "No call to action"}</p>
          {previewIsRemote ? <img src={row.asset_ref} alt={row.headline || "Creative"} /> : <p>{row.asset_ref || "No asset"}</p>}
          <p>{row.live_execution_note || "Live execution is not ready."}</p>
          <hr className="rule" />
          <h3>Assembly</h3>
          <Checks
            items={[
              { label: "Campaign paused", ok: Boolean(row.external_campaign_id) && row.provider_status === "PAUSED" && row.assembly_status === "paused" },
              { label: "Ad set paused", ok: row.ad_set_status === "paused" && Boolean(row.ad_set_external_id) },
              { label: "Creative stored", ok: row.creative_status === "paused" && Boolean(row.creative_external_id) },
              { label: "Ad paused", ok: row.ad_status === "paused" && Boolean(row.ad_external_id) },
              { label: "Not activated", ok: row.status !== "launched" && row.activated !== true },
            ]}
          />
          {row.assembly_blocker ? <p>{row.assembly_blocker}</p> : null}
          <div className="ds-flex" style={{ marginTop: 17 }}>
            <Go href="/content">Open content studio</Go>
            <Go href="/calendar">View calendar</Go>
            <Go href="/insights/attribution">View attribution</Go>
          </div>
        </Panel>
        <Panel title="Budget and execution boundary">
          <div className="between">
            <span className="muted small">Activation</span>
            <StatusPill tone="blocked">Not activated</StatusPill>
          </div>
          <Line label="Proposed budget" value={`${row.currency || ""} ${money(row.budget)}`.trim()} />
          <Line label="Recorded spend" value={spendRecorded ? money(row.spent) : "Not recorded"} />
          <Line label="Impressions" value={spendRecorded ? String(row.impressions ?? 0) : "Not read back"} />
          <Line label="Clicks" value={spendRecorded ? String(row.clicks ?? 0) : "Not read back"} />
          <Line label="Conversions" value={spendRecorded ? String(row.conversions ?? 0) : "Not read back"} />
          <h3>Attributed enquiries</h3>
          {(row.enquiries || []).length === 0 ? <p>No attributed enquiry is stored.</p> : (row.enquiries || []).map((enquiry) => (
            <p key={enquiry.capture_id}>
              {enquiry.first_touch ? "First enquiry" : "Later enquiry"} · {enquiry.status}
              {enquiry.lead_id ? <Go href={`/leads/${enquiry.lead_id}`}>Open journey</Go> : " · no lead"}
            </p>
          ))}
          <Line label="Provider" value={row.provider || "Not connected"} />
          <Line label="New channel" value="Manager approval required" />
          <Line label="Budget increase" value="Manager approval required" />
          <Line label="Activation" value="Not authorized" />
          <hr className="rule" />
          <Go href="/policies">Inspect grant</Go>
        </Panel>
      </div>
    </div>
  );
}
