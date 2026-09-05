"use client";

import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { Timeline } from "@/components/timeline";
import { Badge, Button, CheckField, Drawer, Field, FormActions, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { fullName } from "@/lib/format";
import type { Contact } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

export default function ContactDetailPage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const form = useForm<Contact>();
  const query = useQuery({
    queryKey: ["contact", params.id],
    queryFn: async () => (await api<Contact>(`/api/v1/contacts/${params.id}`)).data,
    enabled: can("contacts.read"),
  });
  const save = useMutation({
    mutationFn: (body: Contact) =>
      api(`/api/v1/contacts/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          account_id: body.account_id,
          first_name: body.first_name,
          last_name: body.last_name,
          email: body.email,
          phone: body.phone,
          title: body.title,
          seniority: body.seniority,
          department: body.department,
          buying_role: body.buying_role,
          consent_email: body.consent_email,
          opt_out: body.opt_out,
        }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["contact", params.id] });
      setOpen(false);
    },
  });

  if (!can("contacts.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState message="This contact is not in your tenant." />;
  const contact = query.data;

  return (
    <div>
      <PageHeader
        eyebrow="Committee member"
        title={fullName(contact.first_name, contact.last_name)}
        subtitle={`${contact.account_name || "No company"} · ${contact.title || "Untitled"} · ${contact.buying_role || "role unknown"}`}
        actions={
          can("contacts.write") ? (
            <Button
              onClick={() => {
                form.reset(contact);
                setOpen(true);
              }}
            >
              Edit
            </Button>
          ) : null
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Identity</p>
          <ul className="mt-4 space-y-3 text-sm">
            <li className="flex justify-between gap-4">
              <span className="text-[var(--muted)]">Company</span>
              <span className="text-right font-medium">{contact.account_name || "—"}</span>
            </li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Email</span>{contact.email || "—"}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Phone</span>{contact.phone || "—"}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Seniority</span>{contact.seniority || "—"}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Department</span>{contact.department || "—"}</li>
            <li className="flex justify-between">
              <span className="text-[var(--muted)]">Consent</span>
              <Badge tone={contact.opt_out ? "rose" : contact.consent_email ? "ok" : "neutral"}>
                {contact.opt_out ? "opted out" : contact.consent_email ? "email ok" : "no consent"}
              </Badge>
            </li>
          </ul>
          {contact.account_id ? (
            <Link href={`/accounts/${contact.account_id}`} className="mt-6 inline-block text-sm text-brand">
              Open {contact.account_name || "account"}
            </Link>
          ) : null}
        </div>
        <div className="lg:col-span-2">
          <h2 className="mb-4 text-xl font-semibold text-navy">Ledger</h2>
          <Timeline entityType="contact" entityId={contact.id} />
        </div>
      </div>
      <Drawer open={open} title="Edit contact" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => save.mutate(values))} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name"><Input {...form.register("first_name", { required: true })} /></Field>
            <Field label="Last name"><Input {...form.register("last_name", { required: true })} /></Field>
          </div>
          <Field label="Email"><Input {...form.register("email")} /></Field>
          <Field label="Phone"><Input {...form.register("phone")} /></Field>
          <Field label="Title"><Input {...form.register("title")} /></Field>
          <Field label="Buying role"><Input {...form.register("buying_role")} /></Field>
          <CheckField label="Email consent" {...form.register("consent_email")} />
          <CheckField label="Opted out" {...form.register("opt_out")} />
          <FormActions pending={save.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
    </div>
  );
}
