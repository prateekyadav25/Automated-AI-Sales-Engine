"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState } from "@/components/states";
import { Badge, Button, Field, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { ImportPreview } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

const ENTITIES = [
  { value: "accounts", label: "Accounts", permission: "accounts.write" },
  { value: "contacts", label: "Contacts", permission: "contacts.write" },
  { value: "leads", label: "Leads", permission: "leads.write" },
];

export default function ImportsPage() {
  const { can } = useAuth();
  const allowed = ENTITIES.filter((item) => can(item.permission));
  const [entity, setEntity] = useState(allowed[0]?.value ?? "leads");
  const [csv, setCsv] = useState("first_name,last_name,company_name,email\nPriya,Nair,Harbor Steel,priya@harbor.example");
  const preview = useMutation({
    mutationFn: () =>
      api<ImportPreview>("/api/v1/imports/preview", {
        method: "POST",
        body: JSON.stringify({ entity, csv_text: csv }),
      }),
  });
  const commit = useMutation({
    mutationFn: () =>
      api("/api/v1/imports/commit", {
        method: "POST",
        body: JSON.stringify({ entity, rows: preview.data?.data?.rows ?? [] }),
      }),
  });

  if (!allowed.length) return <DeniedState />;
  const data = preview.data?.data;
  const result = commit.data?.data as { created?: number } | undefined;

  return (
    <div>
      <PageHeader
        eyebrow="Ingest"
        title="Import"
        subtitle="Preview is mandatory. Commit writes at most 200 rows and never invents columns."
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="panel p-5">
          <Field label="Entity">
            <Select value={entity} onChange={(event) => setEntity(event.target.value)}>
              {allowed.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </Select>
          </Field>
          <div className="mt-4">
            <Field label="CSV">
              <Textarea rows={12} value={csv} onChange={(event) => setCsv(event.target.value)} />
            </Field>
          </div>
          <div className="mt-6 flex gap-2">
            <Button variant="line" onClick={() => preview.mutate()}>Preview</Button>
            <Button disabled={!data || data.errors.length > 0} onClick={() => commit.mutate()}>
              Commit
            </Button>
          </div>
          {preview.isError ? <p className="mt-3 text-sm text-[#e08b7a]">Preview failed.</p> : null}
          {result?.created != null ? <p className="mt-3 text-sm text-brand">{result.created} records written.</p> : null}
        </div>
        <div className="panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <p className="text-sm text-ink">Preview</p>
            {data ? <Badge tone={data.errors.length ? "rose" : "ok"}>{data.count} rows</Badge> : null}
          </div>
          {!data ? (
            <EmptyState title="No preview yet" body="Paste a headered CSV and preview before anything is written." />
          ) : (
            <>
              {data.errors.map((error) => (
                <p key={error} className="mb-2 text-sm text-[#e08b7a]">{error}</p>
              ))}
              <div className="overflow-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-[11px] uppercase tracking-[0.14em] text-[var(--muted)]">
                    <tr>
                      {data.columns.map((column) => (
                        <th key={column} className="py-2 pr-3">{column}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.slice(0, 12).map((row, index) => (
                      <tr key={index} className="border-t border-[var(--line)]">
                        {data.columns.map((column) => (
                          <td key={column} className="py-2 pr-3">{row[column]}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
