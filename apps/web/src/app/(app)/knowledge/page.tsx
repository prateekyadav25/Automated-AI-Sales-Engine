"use client";

import { api, getApiBase, readToken } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Field, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";

type Source = { id: string; title: string; status: string };

export default function KnowledgePage() {
  const { can } = useAuth();
  const [title, setTitle] = useState("Playbook note");
  const query = useQuery({
    queryKey: ["knowledge"],
    queryFn: async () => (await api<Source[]>("/api/v1/ai/knowledge")).data ?? [],
    enabled: can("knowledge.read"),
  });

  async function onUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = (form.elements.namedItem("file") as HTMLInputElement).files?.[0];
    if (!file) return;
    const body = new FormData();
    body.append("title", title);
    body.append("file", file);
    const headers = new Headers();
    const token = readToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    await fetch(`${getApiBase()}/api/v1/ai/knowledge`, { method: "POST", body, headers, credentials: "include" });
    await query.refetch();
    form.reset();
  }

  if (!can("knowledge.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message="Knowledge could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Grounding"
        title="Knowledge"
        subtitle="Tenant-scoped RAG. The copilot cites a source or it abstains."
      />
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        {can("knowledge.write") ? (
          <form onSubmit={onUpload} className="panel p-5 space-y-4">
            <p className="text-sm text-ink">Ingest a playbook</p>
            <Field label="Title"><Input value={title} onChange={(event) => setTitle(event.target.value)} /></Field>
            <Field label="Text or markdown">
              <input name="file" type="file" accept=".txt,.md" className="text-sm text-[var(--muted)]" />
            </Field>
            <Button type="submit">Upload into the vault</Button>
          </form>
        ) : (
          <div className="panel p-5 text-sm text-[var(--muted)]">You can read the vault. Write is reserved.</div>
        )}
        <div>
          {rows.length === 0 ? (
            <EmptyState title="The vault is empty" body="Upload a text playbook so research and drafts have something to cite." />
          ) : (
            <ul className="space-y-2">
              {rows.map((row) => (
                <li key={row.id} className="panel flex items-center justify-between px-4 py-3 text-sm">
                  <span>{row.title}</span>
                  <Badge tone={row.status === "ready" ? "ok" : "gold"}>{labelize(row.status)}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
