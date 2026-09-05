"use client";

import { AutomationTrace } from "@/components/automation-trace";
import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { Timeline } from "@/components/timeline";
import { Badge, Button, Drawer, Field, FormActions, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { OWNERSHIP, TIERS } from "@/lib/constants";
import { fullName, labelize, money } from "@/lib/format";
import type { Account, AccountContext, AccountLifecycle } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

export default function AccountDetailPage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<Account>();
  const query = useQuery({
    queryKey: ["account-context", params.id],
    queryFn: async () => (await api<AccountContext>(`/api/v1/accounts/${params.id}/context`)).data,
    enabled: can("accounts.read"),
  });
  const life = useQuery({
    queryKey: ["account-lifecycle", params.id],
    queryFn: async () => (await api<AccountLifecycle>(`/api/v1/lifecycle/accounts/${params.id}`)).data,
    enabled: can("accounts.read"),
  });

  const save = useMutation({
    mutationFn: (body: Account) =>
      api(`/api/v1/accounts/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: body.name,
          industry: body.industry,
          website: body.website,
          domain: body.domain,
          hq_country: body.hq_country,
          employee_count: body.employee_count,
          annual_revenue: body.annual_revenue,
          ownership: body.ownership,
          target_tier: body.target_tier,
          notes: body.notes,
        }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["account-context", params.id] });
      setOpen(false);
    },
  });
  const research = useMutation({
    mutationFn: () => api(`/api/v1/ai/research/accounts/${params.id}`, { method: "POST" }),
  });
  const prep = useMutation({
    mutationFn: () => api(`/api/v1/ai/meeting-prep/accounts/${params.id}`, { method: "POST" }),
  });

  if (!can("accounts.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Assembling the 360" />;
  if (query.isError || !query.data) return <ErrorState message="This account is not in your tenant." />;

  const { account, contacts, opportunities, tasks } = query.data;
  const brief = (research.data?.data ?? prep.data?.data) as { brief?: string; is_mock?: boolean; provider?: string } | undefined;

  return (
    <div>
      <PageHeader
        eyebrow="Account 360"
        title={account.name}
        subtitle={`${account.industry || "Unclassified"} · ${account.hq_country || "No HQ"} · ${labelize(account.ownership)}`}
        actions={
          <>
            {can("accounts.write") ? (
              <Button
                variant="line"
                onClick={() => {
                  form.reset(account);
                  setOpen(true);
                }}
              >
                Edit
              </Button>
            ) : null}
            {can("ai.research") ? (
              <Button variant="ghost" onClick={() => research.mutate()}>
                Research
              </Button>
            ) : null}
            {can("ai.research") ? <Button onClick={() => prep.mutate()}>Meeting prep</Button> : null}
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-4">
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Firmographics</p>
          <ul className="mt-4 space-y-3 text-sm">
            <li className="flex justify-between"><span className="text-[var(--muted)]">Domain</span>{account.domain || "—"}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Website</span>{account.website || "—"}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Employees</span>{account.employee_count ?? "—"}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Revenue</span>{account.annual_revenue ? money(account.annual_revenue) : "—"}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Tier</span>{labelize(account.target_tier)}</li>
          </ul>
        </div>
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Committee</p>
          <div className="mt-4 space-y-3">
            {contacts.length === 0 ? <p className="text-sm text-[var(--muted)]">No buying-committee members yet.</p> : contacts.map((row) => (
              <Link key={row.id} href={`/contacts/${row.id}`} className="block rounded-xl border border-[var(--line)] px-3 py-3 hover:border-brand/40">
                <p>{fullName(row.first_name, row.last_name)}</p>
                <p className="text-xs text-[var(--muted)]">{row.title || "Untitled"} · {row.buying_role || "role unknown"}</p>
              </Link>
            ))}
          </div>
        </div>
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Pipeline</p>
          <div className="mt-4 space-y-3">
            {opportunities.length === 0 ? <p className="text-sm text-[var(--muted)]">No live opportunities.</p> : opportunities.map((row) => (
              <Link key={row.id} href={`/opportunities/${row.id}`} className="block rounded-xl border border-[var(--line)] px-3 py-3 hover:border-brand/40">
                <p>{row.name}</p>
                <p className="text-xs text-[var(--muted)]">{labelize(row.stage)} · {money(row.amount)}</p>
              </Link>
            ))}
          </div>
        </div>
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Work</p>
          <div className="mt-4 space-y-3">
            {tasks.length === 0 ? <p className="text-sm text-[var(--muted)]">No account tasks.</p> : tasks.map((row) => (
              <div key={row.id} className="rounded-xl border border-[var(--line)] px-3 py-3">
                <p>{row.title}</p>
                <p className="text-xs text-[var(--muted)]">{labelize(row.status)} · {labelize(row.priority)}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
      {life.data ? (
        <div className="mt-4 grid gap-4 xl:grid-cols-4">
          <div className="panel p-5">
            <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Health</p>
            <p className="mt-3 text-3xl font-semibold text-navy">{life.data.health?.total ?? "—"}</p>
            <p className="mt-2 text-xs text-[var(--muted)]">{life.data.health?.version ?? "No customer yet"}</p>
          </div>
          <div className="panel p-5">
            <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Meetings</p>
            <p className="mt-3 text-3xl font-semibold text-navy">{life.data.meetings.length}</p>
          </div>
          <div className="panel p-5">
            <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Quotes</p>
            <p className="mt-3 text-3xl font-semibold text-navy">{life.data.quotes.length}</p>
          </div>
          <div className="panel p-5">
            <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Whitespace</p>
            <p className="mt-3 text-3xl font-semibold text-navy">{life.data.whitespace.length}</p>
          </div>
        </div>
      ) : null}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div className="panel p-5">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm text-ink">Intelligence brief</p>
            {brief?.is_mock ? <Badge tone="gold">Mock provider</Badge> : null}
          </div>
          <p className="whitespace-pre-wrap text-sm leading-7 text-[var(--muted)]">
            {brief?.brief ?? "Run research or meeting prep. The model only speaks from tools."}
          </p>
        </div>
        <AutomationTrace entityType="account" entityId={account.id} />
      </div>
      <div className="mt-4">
        <h2 className="mb-4 text-xl font-semibold text-navy">Ledger</h2>
        <Timeline entityType="account" entityId={account.id} />
      </div>
      <Drawer open={open} title="Edit account" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => save.mutate(values))} className="space-y-4">
          <Field label="Name"><Input {...form.register("name", { required: true })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Industry"><Input {...form.register("industry")} /></Field>
            <Field label="HQ country"><Input {...form.register("hq_country")} /></Field>
          </div>
          <Field label="Notes"><Textarea rows={4} {...form.register("notes")} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Ownership">
              <Select {...form.register("ownership")}>
                {OWNERSHIP.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
              </Select>
            </Field>
            <Field label="Tier">
              <Select {...form.register("target_tier")}>
                {TIERS.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
              </Select>
            </Field>
          </div>
          <FormActions pending={save.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
    </div>
  );
}
