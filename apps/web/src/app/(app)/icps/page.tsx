"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, CheckField, Drawer, Field, FormActions, Input, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { ICP } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type ICPForm = {
  name: string;
  industries: string;
  geographies: string;
  min_employees: number | null;
  description: string;
  is_default: boolean;
};

export default function ICPsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<ICPForm>({
    defaultValues: { name: "", industries: "", geographies: "", min_employees: null, description: "", is_default: false },
  });
  const query = useQuery({
    queryKey: ["icps"],
    queryFn: async () => (await api<ICP[]>("/api/v1/icps")).data ?? [],
    enabled: can("icps.read"),
  });
  const create = useMutation({
    mutationFn: (body: ICPForm) =>
      api("/api/v1/icps", {
        method: "POST",
        body: JSON.stringify({ ...body, min_employees: body.min_employees ? Number(body.min_employees) : null }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["icps"] });
      setOpen(false);
      form.reset();
    },
  });

  if (!can("icps.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message="ICPs could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Step 1 · Start here"
        title="Who we sell to"
        subtitle="Set or confirm the default ICP first. Autopilot and lead scores read this. The model never invents a fit number."
        actions={can("icps.write") ? <Button onClick={() => setOpen(true)}>Define an ICP</Button> : null}
      />
      {rows.length === 0 ? (
        <EmptyState title="No profile yet" body="Define industries, geography, and size so lead scoring has a house standard." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {rows.map((row) => (
            <article key={row.id} className="panel p-5">
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-xl font-semibold text-navy">{row.name}</h2>
                {row.is_default ? <Badge tone="gold">Default</Badge> : null}
              </div>
              <p className="mt-3 text-sm leading-6 text-[var(--muted)]">{row.description || "No narrative yet."}</p>
              <div className="mt-4 space-y-3 text-sm">
                <div>
                  <p className="text-[var(--muted)]">Industries</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {(row.industries || "")
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean)
                      .map((item) => (
                        <Badge key={item} tone="blue">
                          {item}
                        </Badge>
                      ))}
                    {!row.industries ? <span>—</span> : null}
                  </div>
                </div>
                <div>
                  <p className="text-[var(--muted)]">Geographies</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {(row.geographies || "")
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean)
                      .map((item) => (
                        <Badge key={item} tone="neutral">
                          {item}
                        </Badge>
                      ))}
                    {!row.geographies ? <span>—</span> : null}
                  </div>
                </div>
                <p className="flex justify-between">
                  <span className="text-[var(--muted)]">Min employees</span>
                  <span>{row.min_employees ?? "—"}</span>
                </p>
              </div>
            </article>
          ))}
        </div>
      )}
      <Drawer open={open} title="Define an ICP" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <Field label="Name"><Input {...form.register("name", { required: true })} /></Field>
          <Field label="Industries"><Input {...form.register("industries")} /></Field>
          <Field label="Geographies"><Input {...form.register("geographies")} /></Field>
          <Field label="Min employees"><Input type="number" {...form.register("min_employees")} /></Field>
          <Field label="Description"><Textarea rows={4} {...form.register("description")} /></Field>
          <CheckField label="Default profile" {...form.register("is_default")} />
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} label="Save ICP" />
        </form>
      </Drawer>
    </div>
  );
}
