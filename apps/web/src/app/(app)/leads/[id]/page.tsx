"use client";

import { Checks, Go, initials, Line, Panel } from "@/components/ds";
import { MeetingBooking } from "@/components/meeting-booking";
import { VoiceHandoffPanel } from "@/components/voice-handoff";
import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { AutomationTrace } from "@/components/automation-trace";
import { Timeline } from "@/components/timeline";
import { Badge, Button, CheckField, Drawer, Field, FormActions, Input, Score, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { LEAD_STATUSES } from "@/lib/constants";
import { fullName, labelize } from "@/lib/format";
import type { Conversation, Lead, Meeting } from "@/lib/types";
import { ApiError, api } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

type AssessmentFact = { facet: string; fact_class: string; value: string };
type Assessment = {
  coverage_known: number;
  coverage_required: number;
  confidence: string;
  response_eligible: boolean;
  outbound_eligible?: boolean;
  meeting_eligible: boolean;
  sales_qualified: boolean;
  not_a_fit: boolean;
  next_action: string;
  facts: AssessmentFact[];
};
type NextAction = { action?: string; reason?: string; steps?: string[] };
type WrittenDraft = { subject?: string; body?: string; note?: string };
type TeamMember = { id: string; name: string; email: string; team_name?: string };

export default function LeadDetailPage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["lead", params.id],
    queryFn: async () => (await api<Lead>(`/api/v1/leads/${params.id}`)).data,
    enabled: can("leads.read"),
  });
  const members = useQuery({
    queryKey: ["lead-assignees"],
    queryFn: async () => (await api<TeamMember[]>("/api/v1/leads/assignees")).data ?? [],
    enabled: can("leads.read"),
  });
  const assessment = useQuery({
    queryKey: ["lead-assessment", params.id],
    queryFn: async () => (await api<Assessment>(`/api/v1/leads/${params.id}/assessment`)).data,
    enabled: can("leads.read"),
  });
  const meetings = useQuery({
    queryKey: ["meetings"],
    queryFn: async () => (await api<Meeting[]>("/api/v1/lifecycle/meetings")).data ?? [],
    enabled: can("meetings.read"),
  });
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: async () => (await api<Conversation[]>("/api/v1/lifecycle/conversations")).data ?? [],
    enabled: can("conversations.read"),
  });
  const form = useForm<Lead>();

  const save = useMutation({
    mutationFn: (body: Lead) =>
      api(`/api/v1/leads/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          first_name: body.first_name,
          last_name: body.last_name,
          email: body.email,
          company_name: body.company_name,
          title: body.title,
          status: body.status,
          source: body.source,
          channel: body.channel,
          notes: body.notes,
          intent_score: body.intent_score,
          engagement_score: body.engagement_score,
          has_buying_trigger: body.has_buying_trigger,
          consent_email: body.consent_email,
          opt_out: body.opt_out,
          account_id: body.account_id,
        }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["lead", params.id] });
      setOpen(false);
    },
  });
  const score = useMutation({
    mutationFn: () => api(`/api/v1/leads/${params.id}/score`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["lead", params.id] }),
  });
  const nba = useMutation({
    mutationFn: async () => {
      const guide = await api<NextAction>(`/api/v1/leads/${params.id}/nba`, { method: "POST" });
      if (!can("ai.draft")) return { guide: guide.data ?? {}, email: null, whatsapp: null, draftError: "" };
      const [emailResult, whatsappResult] = await Promise.allSettled([
        api<WrittenDraft>("/api/v1/ai/drafts/email", {
          method: "POST",
          body: JSON.stringify({ entity_type: "lead", entity_id: params.id, intent: "first_touch", send: false }),
        }),
        api<WrittenDraft>("/api/v1/ai/drafts/whatsapp", {
          method: "POST",
          body: JSON.stringify({ entity_type: "lead", entity_id: params.id }),
        }),
      ]);
      const email = emailResult.status === "fulfilled" ? emailResult.value.data ?? null : null;
      const whatsapp = whatsappResult.status === "fulfilled" ? whatsappResult.value.data ?? null : null;
      const failed = [emailResult, whatsappResult].filter((item) => item.status === "rejected");
      const draftError = failed.length
        ? failed.map((item) => (item.reason instanceof ApiError ? item.reason.message : "A draft could not be written.")).join(" ")
        : "";
      return { guide: guide.data ?? {}, email, whatsapp, draftError };
    },
  });
  const assign = useMutation({
    mutationFn: (ownerId: string) =>
      api(`/api/v1/leads/${params.id}/assign`, {
        method: "POST",
        body: JSON.stringify({ owner_id: ownerId || null }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["lead", params.id] });
      void client.invalidateQueries({ queryKey: ["leads"] });
      void client.invalidateQueries({ queryKey: ["activities", "lead", params.id] });
    },
  });
  const draft = useMutation({
    mutationFn: () =>
      api("/api/v1/ai/drafts/email", {
        method: "POST",
        body: JSON.stringify({ entity_type: "lead", entity_id: params.id, send: false }),
      }),
  });

  if (!can("leads.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Opening the dossier" />;
  if (query.isError || !query.data) return <ErrorState message="This lead is not in your tenant." />;
  const lead = query.data;
  const parts = lead.latest_score;
  const guide = nba.data?.guide;
  const draftBody = draft.data?.data as WrittenDraft | undefined;
  const emailDraft = nba.data?.email ?? draftBody ?? null;
  const whatsappDraft = nba.data?.whatsapp ?? null;

  return (
    <div>
      <PageHeader
        eyebrow="Lead dossier"
        title={fullName(lead.first_name, lead.last_name)}
        subtitle={`${lead.title || "Untitled"} · ${lead.company_name || "No company"}`}
        actions={
          <>
            {can("leads.write") ? (
              <Button
                variant="line"
                onClick={() => {
                  form.reset(lead);
                  setOpen(true);
                }}
              >
                Edit
              </Button>
            ) : null}
            {can("leads.score") ? (
              <Button variant="ghost" onClick={() => score.mutate()}>
                Recalculate score now
              </Button>
            ) : null}
            {can("ai.draft") ? <Button onClick={() => draft.mutate()}>Draft email</Button> : null}
          </>
        }
      />
      {assessment.isLoading ? <LoadingState label="Loading the assessment" /> : null}
      {assessment.isError ? <ErrorState message="The assessment could not be loaded." /> : null}
      {assessment.data ? (
        <section className="panel" style={{ marginBottom: 16 }}>
          <header className="panel-head"><h2>Assessment</h2></header>
          <div className="panel-body">
            <div className="line-item"><span>Coverage</span><span>{assessment.data.coverage_known}/{assessment.data.coverage_required}</span></div>
            <div className="line-item"><span>Confidence</span><span>{assessment.data.confidence}</span></div>
            <div className="line-item"><span>Response</span><span>{assessment.data.response_eligible ? "Eligible" : "Not eligible"}</span></div>
            <div className="line-item"><span>Outbound</span><span>{assessment.data.outbound_eligible ? "Eligible" : "Not eligible"}</span></div>
            <div className="line-item"><span>Discovery meeting</span><span>{assessment.data.meeting_eligible ? "Eligible" : "Not eligible"}</span></div>
            <div className="line-item"><span>Sales qualification</span><span>{assessment.data.sales_qualified ? "Qualified" : "Not qualified"}</span></div>
            <div className="line-item"><span>Next action</span><span>{labelize(assessment.data.next_action)}</span></div>
            {assessment.data.facts.filter((fact) => fact.fact_class !== "unknown").map((fact) => (
              <div className="line-item" key={fact.facet}><span>{labelize(fact.facet)}</span><span>{fact.fact_class}{fact.value ? ` · ${fact.value}` : ""}</span></div>
            ))}
          </div>
        </section>
      ) : null}
      <div className="ds-grid wide">
        <Panel title="Lead context">
          <div className="ds-flex">
            <span className="avatar square">{initials(fullName(lead.first_name, lead.last_name))}</span>
            <div>
              <h2>{fullName(lead.first_name, lead.last_name)}</h2>
              <div className="small muted">{lead.title || "Title not recorded"} · {lead.company_name || "No company"}</div>
            </div>
            <span className="ds-grow" />
            <Badge tone={lead.status === "qualified" ? "ok" : "blue"}>{labelize(lead.status)}</Badge>
          </div>
          <hr className="rule" />
          <Line label="Fit assessment" value={parts?.total != null ? `${parts.total} / 100 · evidence attached` : "Not scored"} />
          <Line label="Source" value={lead.source || "Not recorded"} />
          {lead.native_status ? (
            <>
              <Line label="Native form" value={`${lead.native_platform || "Meta"} · ${lead.native_form_id || "form not recorded"} · ${lead.native_status}`} />
              <Line label="Mapped product" value={lead.native_product || "No product is mapped"} />
              <Line label="Attribution" value={lead.native_attribution || "Unattributed"} />
              <Line label="Permission evidence" value={lead.native_permission || "Permission was not established"} />
              <Line label="Missing fields" value={lead.native_missing || "Nothing further is listed"} />
              <Line label="Acknowledgement" value={lead.native_acknowledgement || "Not prepared"} />
              <Line label="Review" value={lead.native_review || "No review blocker"} />
            </>
          ) : null}
          <Line label="Selected product" value={lead.product_name || "No product is bound"} />
          <Line label="Offer" value={lead.offer_label || "No offer or tier is stored"} />
          <Line label="Enrichment" value={lead.enrichment_state ? labelize(lead.enrichment_state) : "Not started"} />
          <Line label="Missing" value={lead.missing_information || "Nothing further is listed"} />
          <Line label="Channel eligibility" value={lead.eligibility ? labelize(lead.eligibility) : "Not assessed"} />
          <Line label="Next action" value={lead.next_action || "No next action is stored"} />
          <Line label="Draft approval" value={lead.approval_id || "No outbound draft"} />
          <Line label="Channel" value={lead.channel || "Not recorded"} />
          <Line label="Contact eligibility" value={lead.opt_out ? "Opted out" : lead.consent_email ? "Email permitted · current" : "Consent not recorded"} />
          <Line label="Buying trigger" value={lead.has_buying_trigger ? "Recorded" : "Not recorded"} />
          <Line label="Assigned to" value={lead.owner_name || "Unassigned"} />
          <div className="ds-flex" style={{ marginTop: 18 }}>
            {lead.account_id ? <Go href={`/accounts/${lead.account_id}`}>Account</Go> : null}
            <Go href="/contacts">Contact</Go>
            <Go href="/meetings">Meeting</Go>
            <Go href="/automation/runs">Execution</Go>
          </div>
        </Panel>
        <Panel title="Qualification evidence">
          <Checks
            items={[
              { label: "Business need identified", ok: Boolean(lead.notes || lead.has_buying_trigger) },
              { label: "Sponsor relationship confirmed", ok: lead.status === "qualified" || lead.status === "converted" },
              { label: "Permitted contact scope present", ok: lead.consent_email && !lead.opt_out },
              { label: "Technical evaluator mapped", ok: Boolean(lead.title) },
              { label: "Success criteria and timing confirmed", ok: lead.status === "qualified" },
            ]}
          />
          <hr className="rule" />
          <span className="small muted">The meeting outcome controls the opportunity handoff. A booking does not record attendance.</span>
          {(conversations.data ?? []).flatMap((item) => (
            item.lead_id === lead.id && item.voice ? [
              <div key={item.id} style={{ marginTop: 16 }}>
                <VoiceHandoffPanel voice={item.voice} />
              </div>,
            ] : []
          ))}
          {(meetings.data ?? []).filter((item) => item.lead_id === lead.id).map((item) => (
            <div key={item.id} style={{ marginTop: 16 }}>
              <MeetingBooking meeting={item} />
              <Go href={`/meetings/${item.id}`}>Open meeting</Go>
            </div>
          ))}
          <div style={{ marginTop: 16 }}>
            <Go href="/meetings" primary>Record meeting outcome</Go>
          </div>
          <Button variant="line" disabled={nba.isPending} onClick={() => nba.mutate()}>
            {nba.isPending ? "Writing…" : "Next best action"}
          </Button>
          {guide?.action ? <p>{guide.action}</p> : null}
          {guide?.reason ? <p className="small muted">{guide.reason}</p> : null}
        </Panel>
      </div>
      <div className="grid gap-4 xl:grid-cols-3 section-gap">
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Score</p>
          <div className="mt-3 flex items-end gap-3">
            <p className="text-5xl font-semibold text-navy">{parts?.total ?? "—"}</p>
            <Score value={parts?.total} />
          </div>
          <p className="mt-3 text-sm leading-6 text-[var(--muted)]">{parts?.reasons || "Score the lead to persist a breakdown."}</p>
          {parts ? (
            <ul className="mt-5 space-y-2 text-sm">
              {[
                ["ICP fit", parts.icp_fit],
                ["Intent", parts.intent],
                ["Engagement", parts.engagement],
                ["Persona", parts.persona],
                ["Company", parts.company_potential],
                ["Trigger", parts.buying_trigger],
                ["Timing", parts.timing],
              ].map(([label, value]) => (
                <li key={String(label)} className="flex justify-between">
                  <span className="text-[var(--muted)]">{label}</span>
                  {value}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Record</p>
          <ul className="mt-4 space-y-3 text-sm">
            <li className="flex justify-between"><span className="text-[var(--muted)]">Status</span><Badge>{labelize(lead.status)}</Badge></li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Source</span>{lead.source || "—"}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Channel</span>{lead.channel || "—"}</li>
            <li className="flex justify-between"><span className="text-[var(--muted)]">Consent</span>{lead.opt_out ? "opted out" : lead.consent_email ? "email ok" : "none"}</li>
          </ul>
          <Field label="Team member">
            <Select
              className="mt-2 w-full"
              value={lead.owner_id ?? ""}
              disabled={!can("leads.write") || assign.isPending}
              onChange={(event) => assign.mutate(event.target.value)}
            >
              <option value="">Unassigned</option>
              {(members.data ?? []).map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}{member.team_name ? ` · ${member.team_name}` : ""}
                </option>
              ))}
            </Select>
          </Field>
          {assign.isError ? (
            <p className="mt-2 text-sm leading-6 text-red-700">
              {assign.error instanceof ApiError ? assign.error.message : "This lead could not be assigned."}
            </p>
          ) : null}
          <Button variant="line" className="mt-6" disabled={nba.isPending} onClick={() => nba.mutate()}>
            {nba.isPending ? "Writing…" : "Next best action"}
          </Button>
          {guide?.action ? (
            <div className="mt-4">
              <p className="text-sm leading-6 text-ink">{guide.action}</p>
              {guide.reason ? <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{guide.reason}</p> : null}
              {guide.steps && guide.steps.length > 0 ? (
                <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-6">
                  {guide.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="panel p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">Draft</p>
          {nba.isPending ? <p className="mt-3 text-sm leading-6 text-[var(--muted)]">Writing the email and the WhatsApp message…</p> : null}
          {nba.data?.draftError ? <p className="mt-3 text-sm leading-6 text-red-700">{nba.data.draftError}</p> : null}
          {emailDraft?.body || whatsappDraft?.body ? (
            <div className="mt-4 space-y-5">
              {emailDraft?.body ? (
                <section>
                  <h3 className="text-sm font-medium text-ink">Email</h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                    {emailDraft.subject && !emailDraft.body.trim().toLowerCase().startsWith("subject:")
                      ? `${emailDraft.subject}\n\n`
                      : ""}
                    {emailDraft.body}
                  </p>
                  {emailDraft.note ? <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{emailDraft.note}</p> : null}
                </section>
              ) : null}
              {whatsappDraft?.body ? (
                <section>
                  <h3 className="text-sm font-medium text-ink">WhatsApp</h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6">{whatsappDraft.body}</p>
                  {whatsappDraft.note ? <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{whatsappDraft.note}</p> : null}
                </section>
              ) : null}
              <p className="text-sm leading-6 text-[var(--muted)]">These drafts are stored. Nothing is sent from this page.</p>
            </div>
          ) : nba.isPending ? null : (
            <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
              Click Next best action to write the email and the WhatsApp message. Nothing is sent from here.
            </p>
          )}
        </div>
      </div>
      <div className="mt-8 grid gap-4 xl:grid-cols-2">
        <AutomationTrace entityType="lead" entityId={lead.id} />
        <div>
          <h2 className="mb-4 text-xl font-semibold text-navy">Ledger</h2>
          <Timeline entityType="lead" entityId={lead.id} />
        </div>
      </div>
      <Drawer open={open} title="Edit lead" onClose={() => setOpen(false)}>
        <form onSubmit={form.handleSubmit((values) => save.mutate(values))} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name"><Input {...form.register("first_name", { required: true })} /></Field>
            <Field label="Last name"><Input {...form.register("last_name", { required: true })} /></Field>
          </div>
          <Field label="Email"><Input {...form.register("email")} /></Field>
          <Field label="Company"><Input {...form.register("company_name")} /></Field>
          <Field label="Title"><Input {...form.register("title")} /></Field>
          <Field label="Status">
            <Select {...form.register("status")}>
              {LEAD_STATUSES.map((item) => (
                <option key={item} value={item}>{labelize(item)}</option>
              ))}
            </Select>
          </Field>
          <Field label="Notes"><Textarea rows={4} {...form.register("notes")} /></Field>
          <CheckField label="Buying trigger" {...form.register("has_buying_trigger")} />
          <CheckField label="Email consent" {...form.register("consent_email")} />
          <FormActions pending={save.isPending} onCancel={() => setOpen(false)} />
        </form>
      </Drawer>
    </div>
  );
}
