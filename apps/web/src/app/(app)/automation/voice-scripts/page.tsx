"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Field, Input, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

type ScriptVersion = { id: string; version: number; body: string; status: string };
type VoiceScript = { id: string; name: string; status: string; current_version: number; purpose: string; versions: ScriptVersion[] };

export default function VoiceScriptsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [name, setName] = useState("Outbound intro");
  const [body, setBody] = useState("");
  const query = useQuery({
    queryKey: ["voice-scripts"],
    queryFn: async () => (await api<VoiceScript[]>("/api/v1/lifecycle/voice-scripts")).data ?? [],
    enabled: can("conversations.read"),
  });
  const create = useMutation({
    mutationFn: () => api("/api/v1/lifecycle/voice-scripts", { method: "POST", body: JSON.stringify({ name, purpose: "outbound", body }) }),
    onSuccess: () => {
      setBody("");
      void client.invalidateQueries({ queryKey: ["voice-scripts"] });
    },
  });
  const publish = useMutation({
    mutationFn: ({ scriptId, versionId }: { scriptId: string; versionId: string }) =>
      api(`/api/v1/lifecycle/voice-scripts/${scriptId}/publish/${versionId}`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["voice-scripts"] }),
  });

  if (!can("conversations.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading voice scripts" />;
  if (query.isError) return <ErrorState message="Voice scripts could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Voice"
        title="Voice scripts"
        subtitle="Tenant-owned scripts are reviewable here before Vapi or a human handoff uses them."
      />
      {can("conversations.write") ? (
        <section className="panel mb-6 space-y-3 p-4">
          <Field label="Name"><Input value={name} onChange={(event) => setName(event.target.value)} /></Field>
          <Field label="Script body"><Textarea rows={6} value={body} onChange={(event) => setBody(event.target.value)} /></Field>
          <Button onClick={() => create.mutate()} disabled={create.isPending || !name.trim()}>Save draft</Button>
        </section>
      ) : null}
      {rows.length === 0 ? (
        <EmptyState title="No scripts" body="Write a versioned script. Autopilot does not invent call copy." />
      ) : (
        <div className="space-y-4">
          {rows.map((row) => (
            <article key={row.id} className="panel p-5">
              <div className="flex items-center justify-between gap-3">
                <p className="font-semibold text-navy">{row.name}</p>
                <Badge>{row.status}</Badge>
              </div>
              {(row.versions || []).map((version) => (
                <div key={version.id} className="mt-3 border-t border-[var(--line)] pt-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-brand">v{version.version} · {version.status}</p>
                  <pre className="mt-2 whitespace-pre-wrap text-sm">{version.body}</pre>
                  {can("conversations.write") && version.status !== "published" ? (
                    <Button className="mt-2" variant="line" onClick={() => publish.mutate({ scriptId: row.id, versionId: version.id })}>
                      Publish
                    </Button>
                  ) : null}
                </div>
              ))}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
