"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, CheckField, Drawer, Field, FormActions, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelize } from "@/lib/format";
import type { Contact, Conversation } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type Form = { channel: string; subject: string; transcript: string; summary: string; consent: boolean };

export default function ConversationsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [dialOpen, setDialOpen] = useState(false);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const form = useForm<Form>({ defaultValues: { channel: "chat", subject: "", transcript: "", summary: "", consent: false } });
  const dialForm = useForm<{ contact_id: string; consent: boolean }>({ defaultValues: { contact_id: "", consent: false } });
  const query = useQuery({
    queryKey: ["conversations"],
    queryFn: async () => (await api<Conversation[]>("/api/v1/lifecycle/conversations")).data ?? [],
    enabled: can("conversations.read"),
    refetchInterval: 5000,
  });
  const contacts = useQuery({
    queryKey: ["contacts-dial"],
    queryFn: async () => (await api<Contact[]>("/api/v1/contacts?page_size=100")).data ?? [],
    enabled: dialOpen && can("contacts.read"),
  });
  const create = useMutation({
    mutationFn: (body: Form) => api("/api/v1/lifecycle/conversations", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["conversations"] });
      setOpen(false);
      form.reset({ channel: "chat", subject: "", transcript: "", summary: "", consent: false });
    },
  });
  const dial = useMutation({
    mutationFn: (body: { contact_id: string; consent: boolean }) =>
      api("/api/v1/lifecycle/conversations/dial", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["approvals"] });
      setDialOpen(false);
      dialForm.reset();
    },
  });

  if (!can("conversations.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading conversations" />;
  if (query.isError) return <ErrorState message="Conversations could not be assembled." />;
  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Phase 11"
        title="Conversations"
        subtitle="Email threads live here with inbound and outbound messages. Chat and voice transcripts still record manually. Dial requires consent plus an Approval."
        actions={
          can("conversations.write") ? (
            <div className="flex gap-2">
              <Button variant="line" onClick={() => setDialOpen(true)}>Request dial</Button>
              <Button onClick={() => setOpen(true)}>Record</Button>
            </div>
          ) : null
        }
      />
      {rows.length === 0 ? (
        <EmptyState title="No conversations" body="A cold call without consent is refused." />
      ) : (
        <>
          <DataTable
            rows={rows}
            columns={[
              { key: "subject", header: "Subject", cell: (row) => (
                <button className="text-left text-brand" onClick={() => setSelected(row)}>{row.subject || "—"}</button>
              ) },
              { key: "channel", header: "Channel", cell: (row) => labelize(row.channel) },
              { key: "provider", header: "Provider", cell: (row) => row.is_mock ? <Badge tone="gold">Mock</Badge> : row.provider },
              { key: "messages", header: "Messages", cell: (row) => String(row.messages?.length ?? 0) },
              { key: "consent", header: "Consent", cell: (row) => (row.consent ? "yes" : "no") },
            ]}
          />
          <Drawer open={Boolean(selected)} title={selected?.subject || "Thread"} onClose={() => setSelected(null)}>
            {(selected?.messages ?? []).length === 0 ? (
              <p className="text-sm text-[var(--muted)]">{selected?.transcript || selected?.summary || "No email messages on this thread."}</p>
            ) : (
              <ol className="space-y-3">
                {(selected?.messages ?? []).map((message) => (
                  <li key={message.id} className="rounded-lg border border-[var(--line)] p-3">
                    <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
                      {message.direction} · {message.provider} · {message.classification || message.status}
                    </p>
                    <p className="mt-1 text-sm font-medium">{message.subject || "No subject"}</p>
                    <p className="mt-2 whitespace-pre-wrap text-sm text-ink">{message.body_text}</p>
                  </li>
                ))}
              </ol>
            )}
          </Drawer>
        </>
      )}
      <Drawer open={open} title="Record conversation" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <Field label="Channel">
            <Select {...form.register("channel")}>
              <option value="chat">Chat</option>
              <option value="voice">Voice (transcript only)</option>
            </Select>
          </Field>
          <Field label="Subject"><Input {...form.register("subject")} /></Field>
          <Field label="Transcript"><Textarea rows={5} {...form.register("transcript")} /></Field>
          <Field label="Summary"><Textarea rows={3} {...form.register("summary")} /></Field>
          <CheckField label="Consent to store" {...form.register("consent")} />
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
      <Drawer open={dialOpen} title="Request a gated dial" onClose={() => setDialOpen(false)}>
        <form onSubmit={dialForm.handleSubmit((values) => dial.mutate(values))} className="space-y-4">
          <Field label="Contact">
            <Select {...dialForm.register("contact_id", { required: true })}>
              <option value="">Select</option>
              {(contacts.data ?? []).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.first_name} {row.last_name} {row.phone ? `· ${row.phone}` : "· no phone"}
                </option>
              ))}
            </Select>
          </Field>
          <CheckField label="Voice consent" {...dialForm.register("consent")} />
          {dial.isError ? <p className="text-sm text-[#e08b7a]">Dial was refused. Check consent, opt-out, and phone.</p> : null}
          <FormActions pending={dial.isPending} onCancel={() => setDialOpen(false)} label="Queue approval" />
        </form>
      </Drawer>
    </div>
  );
}
