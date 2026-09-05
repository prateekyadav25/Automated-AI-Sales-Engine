"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Drawer, Field, FormActions, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import type { Team, Territory } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

export default function TeamsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState<"team" | "territory" | null>(null);
  const teamForm = useForm({ defaultValues: { name: "", team_type: "sales" } });
  const territoryForm = useForm({ defaultValues: { name: "", region: "" } });

  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: async () => (await api<Team[]>("/api/v1/admin/teams")).data ?? [],
    enabled: can("teams.read"),
  });
  const territories = useQuery({
    queryKey: ["territories"],
    queryFn: async () => (await api<Territory[]>("/api/v1/admin/territories")).data ?? [],
    enabled: can("teams.read"),
  });
  const createTeam = useMutation({
    mutationFn: (body: { name: string; team_type: string }) =>
      api("/api/v1/admin/teams", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["teams"] });
      setOpen(null);
      teamForm.reset();
    },
  });
  const createTerritory = useMutation({
    mutationFn: (body: { name: string; region: string }) =>
      api("/api/v1/admin/territories", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["territories"] });
      setOpen(null);
      territoryForm.reset();
    },
  });

  if (!can("teams.read")) return <DeniedState />;
  if (teams.isLoading || territories.isLoading) return <LoadingState />;
  if (teams.isError || territories.isError) return <ErrorState message="Teams could not be assembled." />;

  return (
    <div>
      <PageHeader
        eyebrow="House"
        title="Teams & territories"
        subtitle="Routing structure for the tenant. No cross-tenant bleed."
        actions={
          can("teams.write") ? (
            <>
              <Button variant="line" onClick={() => setOpen("territory")}>Add territory</Button>
              <Button onClick={() => setOpen("team")}>Add team</Button>
            </>
          ) : null
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <section>
          <p className="mb-3 text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Teams</p>
          {(teams.data ?? []).length === 0 ? (
            <EmptyState title="No teams" body="Create a sales or success team to begin routing." />
          ) : (
            <div className="space-y-2">
              {(teams.data ?? []).map((row) => (
                <article key={row.id} className="panel flex items-center justify-between px-4 py-3">
                  <p>{row.name}</p>
                  <Badge>{labelize(row.team_type)}</Badge>
                </article>
              ))}
            </div>
          )}
        </section>
        <section>
          <p className="mb-3 text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Territories</p>
          {(territories.data ?? []).length === 0 ? (
            <EmptyState title="No territories" body="Region maps stay empty until you define them." />
          ) : (
            <div className="space-y-2">
              {(territories.data ?? []).map((row) => (
                <article key={row.id} className="panel flex items-center justify-between px-4 py-3">
                  <p>{row.name}</p>
                  <span className="text-sm text-[var(--muted)]">{row.region || "—"}</span>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
      <Drawer open={open === "team"} title="Add team" onClose={() => setOpen(null)}>
        <form onSubmit={teamForm.handleSubmit((values) => createTeam.mutate(values))} className="space-y-4">
          <Field label="Name"><Input {...teamForm.register("name", { required: true })} /></Field>
          <Field label="Type"><Input {...teamForm.register("team_type")} /></Field>
          <FormActions pending={createTeam.isPending} onCancel={() => setOpen(null)} label="Create team" />
        </form>
      </Drawer>
      <Drawer open={open === "territory"} title="Add territory" onClose={() => setOpen(null)}>
        <form onSubmit={territoryForm.handleSubmit((values) => createTerritory.mutate(values))} className="space-y-4">
          <Field label="Name"><Input {...territoryForm.register("name", { required: true })} /></Field>
          <Field label="Region"><Input {...territoryForm.register("region")} /></Field>
          <FormActions pending={createTerritory.isPending} onCancel={() => setOpen(null)} label="Create territory" />
        </form>
      </Drawer>
    </div>
  );
}
