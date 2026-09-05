"use client";

import { DataTable } from "@/components/data-table";
import { ListToolbar } from "@/components/list-toolbar";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, CheckField, Drawer, Field, FormActions, Input, Select } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { fullName } from "@/lib/format";
import { qs, useDebounced } from "@/lib/hooks";
import type { Account, Contact } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

type ContactForm = {
  account_id: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  seniority: string;
  department: string;
  buying_role: string;
  consent_email: boolean;
};

export default function ContactsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const search = useDebounced(q);
  const form = useForm<ContactForm>({
    defaultValues: {
      account_id: "",
      first_name: "",
      last_name: "",
      email: "",
      phone: "",
      title: "",
      seniority: "",
      department: "",
      buying_role: "",
      consent_email: false,
    },
  });

  const query = useQuery({
    queryKey: ["contacts", search, page],
    queryFn: () => api<Contact[]>(`/api/v1/contacts${qs({ q: search, page, page_size: 25 })}`),
    enabled: can("contacts.read"),
  });
  const accounts = useQuery({
    queryKey: ["accounts-options"],
    queryFn: async () => (await api<Account[]>("/api/v1/accounts?page_size=100")).data ?? [],
    enabled: open && can("accounts.read"),
  });

  const create = useMutation({
    mutationFn: (body: ContactForm) =>
      api("/api/v1/contacts", {
        method: "POST",
        body: JSON.stringify({ ...body, account_id: body.account_id || null }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["contacts"] });
      setOpen(false);
      form.reset();
    },
  });

  if (!can("contacts.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Reading the committee" />;
  if (query.isError) return <ErrorState message="Contacts could not be assembled." />;
  const rows = query.data?.data ?? [];
  const total = query.data?.meta?.total ?? rows.length;

  return (
    <div>
      <PageHeader
        eyebrow="Buying committee"
        title="Contacts"
        subtitle="Consent and opt-out live on every person. Outreach without consent is refused."
      />
      <ListToolbar
        query={q}
        onQuery={(value) => {
          setQ(value);
          setPage(1);
        }}
        onCreate={can("contacts.write") ? () => setOpen(true) : undefined}
        createLabel="Add a member"
      />
      {rows.length === 0 ? (
        <EmptyState title="No committee yet" body="Attach people to accounts so research and drafts have a human target." />
      ) : (
        <>
          <DataTable
            rows={rows}
            href={(row) => `/contacts/${row.id}`}
            columns={[
              { key: "name", header: "Name", cell: (row) => fullName(row.first_name, row.last_name) },
              { key: "company", header: "Company", cell: (row) => row.account_name || "—" },
              { key: "title", header: "Title", cell: (row) => row.title || "—" },
              { key: "role", header: "Buying role", cell: (row) => row.buying_role || "—" },
              {
                key: "consent",
                header: "Consent",
                cell: (row) => (
                  <Badge tone={row.opt_out ? "rose" : row.consent_email ? "ok" : "neutral"}>
                    {row.opt_out ? "opted out" : row.consent_email ? "email ok" : "no consent"}
                  </Badge>
                ),
              },
            ]}
          />
          <Pagination page={page} pageSize={25} total={total} onPage={setPage} />
        </>
      )}
      <Drawer open={open} title="Add a committee member" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name"><Input {...form.register("first_name", { required: true })} /></Field>
            <Field label="Last name"><Input {...form.register("last_name", { required: true })} /></Field>
          </div>
          <Field label="Account">
            <Select {...form.register("account_id")}>
              <option value="">Unattached</option>
              {(accounts.data ?? []).map((row) => (
                <option key={row.id} value={row.id}>{row.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="Email"><Input type="email" {...form.register("email")} /></Field>
          <Field label="Title"><Input {...form.register("title")} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Department"><Input {...form.register("department")} /></Field>
            <Field label="Buying role"><Input {...form.register("buying_role")} /></Field>
          </div>
          <CheckField label="Email consent" {...form.register("consent_email")} />
          <FormActions pending={create.isPending} onCancel={() => setOpen(false)} label="Add contact" />
        </form>
      </Drawer>
    </div>
  );
}
