"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { ProviderHealth } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

const CREDENTIAL_PROVIDERS = ["linkedin", "meta", "twilio", "vapi", "apify", "exotel", "openai", "recall", "enrichment"];

type IntegrationAccount = {
  id: string;
  provider: string;
  provider_account_id: string;
  status: string;
  scopes: string[];
  capabilities: { gmail?: boolean; calendar?: boolean };
  last_sync_at: string | null;
  last_success_at: string | null;
  last_error: string;
};

type Connector = {
  provider: string;
  name: string;
  state: string;
  live_enabled: boolean;
  webhook_url: string;
  last_sync_at: string | null;
  connected_customers: number;
  stale_customers: number;
  failed_syncs: number;
  last_error: string;
};

type EntityMapping = {
  id: string;
  provider: string;
  entity_type: string;
  external_id: string;
  internal_entity_type: string;
  internal_entity_id: string;
  status: string;
  confidence: number;
};

function IntegrationsBody() {
  const { can } = useAuth();
  const client = useQueryClient();
  const params = useSearchParams();
  const query = useQuery({
    queryKey: ["integrations"],
    queryFn: async () => (await api<IntegrationAccount[]>("/api/v1/integrations")).data ?? [],
    enabled: can("integrations.read"),
    refetchInterval: 5000,
  });
  const providers = useQuery({
    queryKey: ["integration-providers"],
    queryFn: async () => (await api<ProviderHealth[]>("/api/v1/integrations/providers")).data ?? [],
    enabled: can("integrations.read"),
    refetchInterval: 5000,
  });
  const connectors = useQuery({
    queryKey: ["integration-connectors"],
    queryFn: async () => (await api<Connector[]>("/api/v1/integrations/connectors")).data ?? [],
    enabled: can("integrations.read"),
    refetchInterval: 5000,
  });
  const mappings = useQuery({
    queryKey: ["entity-mappings"],
    queryFn: async () => (await api<EntityMapping[]>("/api/v1/integrations/mappings")).data ?? [],
    enabled: can("integrations.read"),
    refetchInterval: 5000,
  });
  const [changeTargets, setChangeTargets] = useState<Record<string, string>>({});
  const [credProvider, setCredProvider] = useState("linkedin");
  const [credToken, setCredToken] = useState("");
  const [credExtra, setCredExtra] = useState("");
  const confirmMapping = useMutation({
    mutationFn: (id: string) => api(`/api/v1/integrations/mappings/${id}/confirm`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["entity-mappings"] }),
  });
  const ignoreMapping = useMutation({
    mutationFn: (id: string) => api(`/api/v1/integrations/mappings/${id}/ignore`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["entity-mappings"] }),
  });
  const changeMapping = useMutation({
    mutationFn: ({ id, internal_entity_id }: { id: string; internal_entity_id: string }) =>
      api(`/api/v1/integrations/mappings/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ internal_entity_type: "customer", internal_entity_id }),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["entity-mappings"] }),
  });
  const connect = useMutation({
    mutationFn: async () =>
      (await api<{ authorization_url: string; configured: boolean }>("/api/v1/integrations/google/connect")).data,
    onSuccess: (data) => {
      if (data?.authorization_url) window.location.href = data.authorization_url;
    },
  });
  const disconnect = useMutation({
    mutationFn: (id: string) => api(`/api/v1/integrations/${id}`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["integrations"] }),
  });
  const unlinkMapping = useMutation({
    mutationFn: (id: string) => api(`/api/v1/integrations/mappings/${id}/unlink`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["entity-mappings"] }),
  });
  const saveCredential = useMutation({
    mutationFn: () =>
      api("/api/v1/integrations/credentials", {
        method: "POST",
        body: JSON.stringify({
          provider: credProvider,
          access_token: credToken,
          extra: credExtra.trim() ? JSON.parse(credExtra) : {},
        }),
      }),
    onSuccess: () => {
      setCredToken("");
      setCredExtra("");
      void client.invalidateQueries({ queryKey: ["integrations"] });
      void client.invalidateQueries({ queryKey: ["integration-providers"] });
    },
  });
  const provision = useMutation({
    mutationFn: () => api("/api/v1/integrations/provision-defaults", { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["integrations"] });
      void client.invalidateQueries({ queryKey: ["integration-providers"] });
    },
  });

  if (!can("integrations.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading integrations" />;
  if (query.isError) return <ErrorState message="Integrations could not be assembled." />;
  const rows = query.data ?? [];
  const google = rows.find((row) => row.provider === "google");
  const notice = params.get("connected") === "google" ? "Google is connected." : params.get("error") ? "Google OAuth did not complete." : "";

  return (
    <div>
      <PageHeader
        eyebrow="House"
        title="Integrations"
        subtitle="Google OAuth is per user. Usage, support, finance, and ERP ingest through signed webhooks. Tokens never appear in this desk."
        actions={
          can("integrations.write") ? (
            <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
              {google?.status === "connected" ? "Reconnect Google" : "Connect Google"}
            </Button>
          ) : null
        }
      />
      {notice ? <p className="mb-4 text-sm text-navy">{notice}</p> : null}
      {can("integrations.write") ? (
        <section className="mb-6 panel p-4" data-testid="provider-credentials">
          <p className="mb-3 text-sm font-semibold text-navy">Tenant ads / voice credentials</p>
          <div className="flex flex-wrap items-end gap-2">
            <select
              className="rounded-md border border-[var(--line)] bg-white px-2 py-1 text-xs"
              value={credProvider}
              onChange={(event) => setCredProvider(event.target.value)}
              aria-label="Credential provider"
            >
              {CREDENTIAL_PROVIDERS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <input
              className="min-w-[12rem] flex-1 rounded-md border border-[var(--line)] bg-white px-2 py-1 text-xs"
              placeholder="Access token"
              value={credToken}
              onChange={(event) => setCredToken(event.target.value)}
            />
            <input
              className="min-w-[12rem] flex-1 rounded-md border border-[var(--line)] bg-white px-2 py-1 text-xs"
              placeholder='Extra JSON e.g. {"account_id":"..."}'
              value={credExtra}
              onChange={(event) => setCredExtra(event.target.value)}
            />
            <Button onClick={() => saveCredential.mutate()} disabled={saveCredential.isPending || !credToken}>
              Save encrypted
            </Button>
            <Button variant="line" onClick={() => provision.mutate()} disabled={provision.isPending}>
              Copy deployment secrets
            </Button>
          </div>
        </section>
      ) : null}
      {providers.data?.length ? (
        <section className="mb-6" data-testid="provider-modes">
          <p className="mb-3 text-sm font-semibold text-navy">Channel modes</p>
          <ul className="grid gap-3 md:grid-cols-2">
            {providers.data
              .filter((row) => ["Apify", "LinkedIn Ads", "Meta Ads", "Voice", "Gmail", "Google Calendar"].includes(row.name))
              .map((row) => (
                <li key={row.name} className="panel p-4" data-testid={`integration-${row.name.toLowerCase().replaceAll(" ", "-")}`}>
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-semibold text-navy">{row.name}</p>
                    <Badge tone={row.mode === "LIVE" ? "ok" : row.mode === "MOCK" ? "gold" : "rose"}>{row.mode || row.state}</Badge>
                  </div>
                  <p className="mt-2 text-xs text-[var(--muted)]">{row.reason}</p>
                </li>
              ))}
          </ul>
        </section>
      ) : null}
      {connectors.data?.length ? (
        <section className="mb-6" data-testid="signal-connectors">
          <p className="mb-3 text-sm font-semibold text-navy">Customer intelligence connectors</p>
          <ul className="grid gap-3 md:grid-cols-2">
            {connectors.data.map((row) => (
              <li key={row.provider} className="panel p-4" data-testid={`connector-${row.provider}`}>
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm font-semibold text-navy">{row.name}</p>
                  <Badge tone={row.state === "LIVE" ? "ok" : "rose"}>{row.state}</Badge>
                </div>
                <p className="mt-2 break-all text-xs text-[var(--muted)]">{row.webhook_url}</p>
                <p className="mt-2 text-xs text-[var(--muted)]">
                  {row.connected_customers} connected · {row.stale_customers} stale · {row.failed_syncs} failed syncs
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {mappings.data?.length ? (
        <section className="mb-6" data-testid="entity-mappings">
          <p className="mb-3 text-sm font-semibold text-navy">Entity mapping review</p>
          <ul className="space-y-3">
            {mappings.data.map((row) => (
              <li key={row.id} className="panel p-4" data-testid={`mapping-${row.id}`}>
                <p className="text-sm font-medium text-navy">
                  {row.provider} {row.entity_type} {row.external_id}
                </p>
                <p className="mt-1 text-xs text-[var(--muted)]">
                  {row.status} · {row.internal_entity_type} {row.internal_entity_id || "unmapped"} · confidence {row.confidence}
                </p>
                {can("integrations.write") && (row.status === "confirmed" || row.status === "mapped") ? (
                  <div className="mt-3">
                    <Button variant="line" data-testid={`unlink-${row.id}`} onClick={() => unlinkMapping.mutate(row.id)}>
                      Unlink and recalc
                    </Button>
                  </div>
                ) : null}
                {can("integrations.write") && row.status === "pending" ? (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button onClick={() => confirmMapping.mutate(row.id)} disabled={confirmMapping.isPending}>
                      Confirm
                    </Button>
                    <Button variant="line" onClick={() => ignoreMapping.mutate(row.id)} disabled={ignoreMapping.isPending}>
                      Ignore
                    </Button>
                    <input
                      className="min-w-[12rem] flex-1 rounded-md border border-[var(--line)] bg-white px-2 py-1 text-xs"
                      placeholder="Customer id to change"
                      value={changeTargets[row.id] ?? ""}
                      onChange={(event) => setChangeTargets((current) => ({ ...current, [row.id]: event.target.value }))}
                    />
                    <Button
                      variant="line"
                      onClick={() =>
                        changeMapping.mutate({ id: row.id, internal_entity_id: (changeTargets[row.id] || row.internal_entity_id).trim() })
                      }
                      disabled={changeMapping.isPending || !(changeTargets[row.id] || row.internal_entity_id)}
                    >
                      Change
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {connect.isError ? <p className="mb-4 text-sm text-[#e08b7a]">Google is not configured on the API.</p> : null}
      {rows.length === 0 ? (
        <EmptyState
          title="No connections"
          body="Connect Google to send live mail and book meetings. Mock providers stay labeled until then."
        />
      ) : (
        <ul className="space-y-3">
          {rows.map((row) => (
            <li key={row.id} className="panel p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-navy">{row.provider_account_id || "Google account"}</p>
                  <p className="mt-1 text-xs text-[var(--muted)]">
                    Last sync {row.last_sync_at ? new Date(row.last_sync_at).toLocaleString() : "never"}
                  </p>
                  {row.last_error ? <p className="mt-1 text-xs text-[#e08b7a]">{row.last_error}</p> : null}
                </div>
                <Badge tone={row.status === "connected" ? "ok" : "rose"}>{row.status}</Badge>
              </div>
              <p className="mt-4 text-sm text-ink">
                Gmail {row.capabilities.gmail ? "ready" : "not granted"} · Calendar {row.capabilities.calendar ? "ready" : "not granted"}
              </p>
              <p className="mt-2 text-xs text-[var(--muted)]">{row.scopes.join(" ") || "No scopes stored"}</p>
              {can("integrations.write") ? (
                <Button className="mt-4" variant="line" onClick={() => disconnect.mutate(row.id)} disabled={disconnect.isPending}>
                  Disconnect
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function IntegrationsPage() {
  return (
    <Suspense fallback={<LoadingState label="Reading integrations" />}>
      <IntegrationsBody />
    </Suspense>
  );
}
