"use client";

import { Line, Notice, Panel } from "@/components/ds";
import { GrowthNav, ProvenanceTag, StatusTag } from "@/components/growth-ui";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, CheckField, Field, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { when } from "@/lib/format";
import { growth, send, type BrandFact, type BrandView, type BusinessEvent, type CalendarItem, type GrowthAccount, type Pillar, type Strategy, type StrategyView } from "@/lib/growth";
import { ApiError } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

const PLATFORM_FORMATS: Record<string, string[]> = { instagram: ["image", "carousel", "reel"], facebook: ["image", "carousel", "reel", "text"] };
const METRICS = ["reach", "engagement", "link_clicks", "enquiries"];

function failure(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

type Draft = {
  objective: string;
  optimization_metric: string;
  pillars: Pillar[];
  audiences: string;
  cadence: Record<string, Record<string, number>>;
  call_to_action: string;
  destination_kind: string;
  destination_form_key_id: string;
  destination_url: string;
  auto_create: boolean;
  auto_schedule: boolean;
  review_terms: string;
  horizon_days: number;
};

function fromStrategy(source: Strategy | null, suggested: Pillar[], defaults: string[]): Draft {
  return {
    objective: source?.objective ?? "",
    optimization_metric: source?.optimization_metric ?? "reach",
    pillars: source?.pillars?.length ? source.pillars : suggested,
    audiences: (source?.audiences ?? []).join(", "),
    cadence: Object.fromEntries(Object.entries(source?.cadence ?? {}).map(([id, plan]) => [id, plan.formats])),
    call_to_action: source?.call_to_action ?? "",
    destination_kind: source?.destination_kind ?? "form",
    destination_form_key_id: source?.destination_form_key_id ?? "",
    destination_url: source?.destination_url ?? "",
    auto_create: source?.auto_create ?? true,
    auto_schedule: source?.auto_schedule ?? false,
    review_terms: (source?.review_terms?.length ? source.review_terms : defaults).join(", "),
    horizon_days: source?.horizon_days ?? 30,
  };
}

function StrategyEditor({ view, accounts, facts, onChanged }: { view: StrategyView; accounts: GrowthAccount[]; facts: BrandFact[]; onChanged: () => void }) {
  const { can } = useAuth();
  const base = view.draft ?? view.active;
  const [draft, setDraft] = useState<Draft>(() => fromStrategy(base, view.suggested_pillars, view.review_terms_default));
  useEffect(() => setDraft(fromStrategy(base, view.suggested_pillars, view.review_terms_default)), [base, view.suggested_pillars, view.review_terms_default]);
  const approved = facts.filter((fact) => fact.state === "approved");
  const byId = useMemo(() => new Map(approved.map((fact) => [fact.id, fact])), [approved]);
  const save = useMutation({
    mutationFn: () =>
      growth<Strategy>(
        "/strategy",
        send(
          {
            objective: draft.objective,
            optimization_metric: draft.optimization_metric,
            pillars: draft.pillars,
            audiences: draft.audiences.split(",").map((item) => item.trim()).filter(Boolean),
            cadence: Object.fromEntries(Object.entries(draft.cadence).map(([id, formats]) => [id, { formats }])),
            call_to_action: draft.call_to_action,
            destination_kind: draft.destination_kind,
            destination_form_key_id: draft.destination_kind === "form" ? draft.destination_form_key_id || null : null,
            destination_url: draft.destination_url,
            auto_create: draft.auto_create,
            auto_schedule: draft.auto_schedule,
            review_terms: draft.review_terms.split(",").map((item) => item.trim()).filter(Boolean),
            horizon_days: draft.horizon_days,
          },
          "PUT",
        ),
      ),
    onSuccess: onChanged,
  });
  const approve = useMutation({ mutationFn: (id: string) => growth<Strategy>(`/strategy/${id}/approve`, { method: "POST" }), onSuccess: onChanged });
  const pause = useMutation({ mutationFn: (paused: boolean) => growth<Strategy>("/strategy/pause", send({ paused })), onSuccess: onChanged });
  const setFormat = (accountId: string, format: string, count: number) =>
    setDraft((current) => {
      const formats = { ...(current.cadence[accountId] ?? {}) };
      if (count > 0) formats[format] = count;
      else delete formats[format];
      const cadence = { ...current.cadence };
      if (Object.keys(formats).length) cadence[accountId] = formats;
      else delete cadence[accountId];
      return { ...current, cadence };
    });
  const editable = can("social_growth.write");
  return (
    <Panel
      title="Strategy"
      extra={
        <span className="flex flex-wrap items-center gap-2">
          {view.active ? (
            <>
              <span className="text-sm text-[var(--muted)]">In force: version {view.active.version}</span>
              <StatusTag status={view.active.status} />
            </>
          ) : (
            <StatusTag status="none" />
          )}
          {view.draft ? <StatusTag status="draft" /> : null}
        </span>
      }
    >
      {approved.length === 0 ? <Notice kind="warn" title="No approved facts" body="Approve brand facts first. Every pillar must cite approved facts, so nothing can be planned without them." /> : null}
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Objective">
            <Input value={draft.objective} onChange={(event) => setDraft({ ...draft, objective: event.target.value })} disabled={!editable} />
          </Field>
          <Field label="Optimize for">
            <Select value={draft.optimization_metric} onChange={(event) => setDraft({ ...draft, optimization_metric: event.target.value })} disabled={!editable}>
              {METRICS.map((metric) => (
                <option key={metric} value={metric}>
                  {metric.replaceAll("_", " ")}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Call to action">
            <Input value={draft.call_to_action} onChange={(event) => setDraft({ ...draft, call_to_action: event.target.value })} disabled={!editable} required />
          </Field>
          <Field label="Audiences (comma separated)">
            <Input value={draft.audiences} onChange={(event) => setDraft({ ...draft, audiences: event.target.value })} disabled={!editable} />
          </Field>
          <Field label="Destination">
            <Select value={draft.destination_kind} onChange={(event) => setDraft({ ...draft, destination_kind: event.target.value })} disabled={!editable}>
              <option value="form">Enquiry form</option>
              <option value="website">Website page</option>
            </Select>
          </Field>
          {draft.destination_kind === "form" ? (
            <Field label="Enquiry form">
              <Select value={draft.destination_form_key_id} onChange={(event) => setDraft({ ...draft, destination_form_key_id: event.target.value })} disabled={!editable}>
                <option value="">Choose a form</option>
                {view.forms.map((form) => (
                  <option key={form.id} value={form.id}>
                    {form.name}
                  </option>
                ))}
              </Select>
            </Field>
          ) : (
            <Field label="Website address (https)">
              <Input value={draft.destination_url} onChange={(event) => setDraft({ ...draft, destination_url: event.target.value })} disabled={!editable} />
            </Field>
          )}
          <Field label="Rolling horizon (days)">
            <Input type="number" min={7} max={30} value={draft.horizon_days} onChange={(event) => setDraft({ ...draft, horizon_days: Number(event.target.value) })} disabled={!editable} />
          </Field>
          <Field label="Terms that always need a person">
            <Input value={draft.review_terms} onChange={(event) => setDraft({ ...draft, review_terms: event.target.value })} disabled={!editable} />
          </Field>
        </div>
        <div className="flex flex-wrap gap-4">
          <CheckField label="Create creative automatically" checked={draft.auto_create} onChange={(event) => setDraft({ ...draft, auto_create: event.target.checked })} disabled={!editable} />
          <CheckField label="Schedule automatically under an execution grant" checked={draft.auto_schedule} onChange={(event) => setDraft({ ...draft, auto_schedule: event.target.checked })} disabled={!editable} />
        </div>
        <div>
          <p className="text-sm font-medium text-navy">Pillars</p>
          {draft.pillars.length === 0 ? <p className="text-sm text-[var(--muted)]">No pillar can be suggested until facts are approved.</p> : null}
          <div className="mt-2 grid gap-3 md:grid-cols-2">
            {draft.pillars.map((pillar, index) => (
              <div key={pillar.key} className="rounded-md border border-[var(--line)] p-3">
                <div className="flex items-center justify-between gap-2">
                  <Input value={pillar.name} disabled={!editable} onChange={(event) => setDraft({ ...draft, pillars: draft.pillars.map((item, position) => (position === index ? { ...item, name: event.target.value } : item)) })} aria-label="Pillar name" />
                  {editable ? (
                    <Button type="button" variant="ghost" onClick={() => setDraft({ ...draft, pillars: draft.pillars.filter((_, position) => position !== index) })}>
                      Remove
                    </Button>
                  ) : null}
                </div>
                <ul className="mt-2 space-y-1 text-xs text-[var(--muted)]">
                  {pillar.fact_ids.map((id) => (
                    <li key={id}>{byId.get(id)?.statement ?? "This fact is no longer approved."}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          {editable && view.suggested_pillars.some((pillar) => !draft.pillars.find((item) => item.key === pillar.key)) ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {view.suggested_pillars
                .filter((pillar) => !draft.pillars.find((item) => item.key === pillar.key))
                .map((pillar) => (
                  <Button key={pillar.key} type="button" variant="ghost" onClick={() => setDraft({ ...draft, pillars: [...draft.pillars, pillar] })}>
                    Add pillar: {pillar.name}
                  </Button>
                ))}
            </div>
          ) : null}
        </div>
        <div>
          <p className="text-sm font-medium text-navy">Weekly cadence by account</p>
          {accounts.length === 0 ? <p className="text-sm text-[var(--muted)]">Connect an account first.</p> : null}
          <div className="mt-2 space-y-2">
            {accounts
              .filter((account) => !["disconnected", "revoked"].includes(account.status))
              .map((account) => (
                <div key={account.id} className="flex flex-wrap items-center gap-3 rounded-md border border-[var(--line)] p-2 text-sm">
                  <span className="min-w-48">
                    {account.platform === "instagram" ? "Instagram" : "Facebook"} · {account.name || account.external_id}
                  </span>
                  <ProvenanceTag value={account.provenance} />
                  {(PLATFORM_FORMATS[account.platform] ?? []).map((format) => (
                    <label key={format} className="flex items-center gap-1 text-xs">
                      {format}
                      <input
                        type="number"
                        min={0}
                        max={14}
                        className="input w-16"
                        value={draft.cadence[account.id]?.[format] ?? 0}
                        disabled={!editable}
                        onChange={(event) => setFormat(account.id, format, Number(event.target.value))}
                        aria-label={`${format} posts per week for ${account.name || account.external_id}`}
                      />
                    </label>
                  ))}
                </div>
              ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {editable ? (
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save draft"}
            </Button>
          ) : null}
          {can("social_growth.approve") && view.draft ? (
            <Button type="button" onClick={() => approve.mutate(view.draft!.id)} disabled={approve.isPending}>
              Approve version {view.draft.version}
            </Button>
          ) : null}
          {can("social_growth.approve") && view.active ? (
            <Button type="button" variant="ghost" onClick={() => pause.mutate(view.active!.status !== "paused")} disabled={pause.isPending}>
              {view.active.status === "paused" ? "Resume strategy" : "Pause strategy"}
            </Button>
          ) : null}
        </div>
        {save.isError ? <ErrorState message={failure(save.error, "The strategy was not saved.")} /> : null}
        {approve.isError ? <ErrorState message={failure(approve.error, "The strategy was not approved.")} /> : null}
        {save.isSuccess ? <Notice kind="good" title="Draft saved" body="A draft does not change what automation follows until it is approved." /> : null}
      </form>
    </Panel>
  );
}

function EventsPanel({ events, facts, onChanged }: { events: BusinessEvent[]; facts: BrandFact[]; onChanged: () => void }) {
  const { can } = useAuth();
  const [form, setForm] = useState({ title: "", kind: "event", starts_on: "", ends_on: "", details: "", source_url: "", fact_ids: [] as string[] });
  const add = useMutation({
    mutationFn: () => growth<BusinessEvent>("/events", send(form)),
    onSuccess: () => {
      setForm({ title: "", kind: "event", starts_on: "", ends_on: "", details: "", source_url: "", fact_ids: [] });
      onChanged();
    },
  });
  const cancel = useMutation({ mutationFn: (id: string) => growth<BusinessEvent>(`/events/${id}`, { method: "DELETE" }), onSuccess: onChanged });
  return (
    <Panel title="Business events">
      {events.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No launch, offer, or date is recorded. The calendar only uses events a person records.</p>
      ) : (
        <ul className="mb-3 space-y-2 text-sm">
          {events.map((event) => (
            <li key={event.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {event.starts_on} to {event.ends_on} · {event.title} <span className="text-xs text-[var(--muted)]">({event.kind})</span>
              </span>
              {can("social_growth.write") ? (
                <Button type="button" variant="ghost" onClick={() => cancel.mutate(event.id)}>
                  Cancel
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {can("social_growth.write") ? (
        <form
          className="grid gap-2 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate();
          }}
        >
          <Field label="Title">
            <Input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required />
          </Field>
          <Field label="Kind">
            <Select value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value })}>
              {["launch", "offer", "holiday", "event", "announcement"].map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Starts">
            <Input type="date" value={form.starts_on} onChange={(event) => setForm({ ...form, starts_on: event.target.value })} required />
          </Field>
          <Field label="Ends">
            <Input type="date" value={form.ends_on} onChange={(event) => setForm({ ...form, ends_on: event.target.value })} required />
          </Field>
          <Field label="Details">
            <Textarea rows={2} value={form.details} onChange={(event) => setForm({ ...form, details: event.target.value })} />
          </Field>
          <Field label="Approved fact to feature">
            <Select value={form.fact_ids[0] ?? ""} onChange={(event) => setForm({ ...form, fact_ids: event.target.value ? [event.target.value] : [] })}>
              <option value="">None</option>
              {facts
                .filter((fact) => fact.state === "approved")
                .map((fact) => (
                  <option key={fact.id} value={fact.id}>
                    {fact.statement.slice(0, 80)}
                  </option>
                ))}
            </Select>
          </Field>
          <div className="md:col-span-2">
            <Button type="submit" variant="ghost" disabled={add.isPending}>
              Record event
            </Button>
            {add.isError ? <ErrorState message={failure(add.error, "The event was not saved.")} /> : null}
          </div>
        </form>
      ) : null}
    </Panel>
  );
}

function BriefDetails({ item }: { item: CalendarItem }) {
  const brief = item.brief;
  return (
    <div className="mt-2 space-y-2 rounded-md border border-[var(--line)] bg-[#101722] p-3 text-xs">
      <p className="text-ink">{brief.rationale}</p>
      <div>
        <p className="font-medium text-navy">Approved facts it may use</p>
        <ul className="space-y-1">
          {(brief.facts ?? []).map((fact) => (
            <li key={fact.id}>
              {fact.statement}{" "}
              <a className="text-brand" href={fact.source_url} target="_blank" rel="noreferrer">
                source
              </a>
            </li>
          ))}
        </ul>
      </div>
      <Line label="Repetition check" value={brief.repetition ? `${brief.repetition.passed ? "Passed" : "Flagged"} · closest ${brief.repetition.max_similarity} (limit ${brief.repetition.threshold})` : "—"} />
      <Line label="Recent posts compared" value={String(brief.prior_content?.length ?? 0)} />
      <Line label="Performance evidence" value={brief.performance ? `${brief.performance.verdict.replaceAll("_", " ")} · ${brief.performance.rule}` : "—"} />
      <Line label="Business event" value={brief.event ? `${brief.event.title} (${brief.event.starts_on} to ${brief.event.ends_on})` : "None"} />
      <Line label="Call to action" value={brief.call_to_action ?? "—"} />
    </div>
  );
}

function CalendarList({ items, onChanged }: { items: CalendarItem[]; onChanged: () => void }) {
  const { can } = useAuth();
  const [open, setOpen] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const act = useMutation({
    mutationFn: async ({ id, path, body }: { id: string; path: string; body?: unknown }) => {
      const result = await growth<Record<string, unknown>>(`/calendar/${id}/${path}`, send(body ?? {}));
      return { id, detail: typeof result.detail === "string" ? result.detail : typeof result.status === "string" ? `Now ${result.status.replaceAll("_", " ")}.` : "Done." };
    },
    onSuccess: ({ id, detail }) => {
      setNotes((current) => ({ ...current, [id]: detail }));
      onChanged();
    },
    onError: (error, variables) => setNotes((current) => ({ ...current, [variables.id]: failure(error, "The request failed.") })),
  });
  const grouped = items.reduce<Record<string, CalendarItem[]>>((acc, item) => {
    (acc[item.local_date] ??= []).push(item);
    return acc;
  }, {});
  return (
    <div className="space-y-4">
      {Object.entries(grouped).map(([day, rows]) => (
        <section key={day}>
          <h3 className="mb-2 text-sm font-semibold text-navy">{new Date(`${day}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" })}</h3>
          <ul className="space-y-2">
            {rows.map((item) => (
              <li key={item.id} className="rounded-md border border-[var(--line)] p-3 text-sm" data-testid="growth-calendar-item" data-item-id={item.id}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="num">{new Date(item.planned_for).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                  <span>{item.platform === "instagram" ? "Instagram" : "Facebook"} · {item.account_name}</span>
                  {item.account_provenance === "fixture" ? <StatusTag status="fixture" /> : null}
                  <span className="text-xs uppercase tracking-[0.1em] text-[var(--muted)]">{item.format}</span>
                  <span className="text-xs text-[var(--muted)]">{item.brief.pillar?.name ?? item.pillar_key}</span>
                  <StatusTag status={item.status} />
                  {item.creative ? <span className="text-xs text-[var(--muted)]">Creative v{item.creative.version} · {item.creative.status.replaceAll("_", " ")}</span> : null}
                  {item.publication?.permalink ? (
                    <a className="text-xs text-brand" href={item.publication.permalink} target="_blank" rel="noreferrer">
                      View post
                    </a>
                  ) : null}
                </div>
                {item.blocker ? <p className="mt-1 text-xs text-[var(--muted)]">{item.blocker}</p> : null}
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button type="button" variant="ghost" onClick={() => setOpen(open === item.id ? null : item.id)}>
                    {open === item.id ? "Hide brief" : "Brief"}
                  </Button>
                  {can("social_growth.write") && ["planned", "blocked", "needs_review", "creative_ready"].includes(item.status) ? (
                    <Button type="button" variant="ghost" disabled={act.isPending} onClick={() => act.mutate({ id: item.id, path: "creative" })}>
                      {item.creative ? "Open creative" : "Produce creative"}
                    </Button>
                  ) : null}
                  {can("social_growth.approve") && item.status === "approved" ? (
                    <Button type="button" disabled={act.isPending} onClick={() => act.mutate({ id: item.id, path: "schedule" })}>
                      Schedule
                    </Button>
                  ) : null}
                  {can("social_growth.write") && !["published", "publishing", "skipped"].includes(item.status) ? (
                    <Button type="button" variant="ghost" disabled={act.isPending} onClick={() => act.mutate({ id: item.id, path: "skip", body: { reason: "Skipped from the calendar." } })}>
                      Skip
                    </Button>
                  ) : null}
                </div>
                {notes[item.id] ? <p className="mt-1 text-xs text-[var(--muted)]">{notes[item.id]}</p> : null}
                {open === item.id ? <BriefDetails item={item} /> : null}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export default function GrowthCalendarPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const enabled = can("social_growth.read");
  const strategy = useQuery({ queryKey: ["growth-strategy"], queryFn: () => growth<StrategyView>("/strategy"), enabled });
  const accounts = useQuery({ queryKey: ["growth-accounts"], queryFn: () => growth<GrowthAccount[]>("/accounts"), enabled });
  const brand = useQuery({ queryKey: ["growth-brand"], queryFn: () => growth<BrandView>("/brand"), enabled });
  const calendar = useQuery({ queryKey: ["growth-calendar"], queryFn: () => growth<{ items: CalendarItem[]; by_status: Record<string, number> }>("/calendar"), enabled });
  const refresh = () => {
    for (const key of ["growth-strategy", "growth-calendar", "growth-overview", "growth-review"]) void client.invalidateQueries({ queryKey: [key] });
  };
  const plan = useMutation({ mutationFn: () => growth<{ detail: string }>("/calendar/plan", { method: "POST" }), onSuccess: refresh });
  if (!enabled) return <DeniedState />;
  if (strategy.isLoading || accounts.isLoading || brand.isLoading || calendar.isLoading) return <LoadingState label="Reading the strategy and calendar" />;
  if (strategy.isError || accounts.isError || brand.isError || calendar.isError || !strategy.data) return <ErrorState message="The strategy or calendar could not be loaded." />;
  const items = calendar.data?.items ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Social growth"
        title="Strategy and rolling calendar"
        subtitle="An approved strategy names the pillars, accounts, cadence, formats, and call to action. The calendar fills the next 30 days inside each account's posting window. Every slot explains which approved facts it may use and why."
        actions={
          can("social_growth.write") ? (
            <Button type="button" onClick={() => plan.mutate()} disabled={plan.isPending || !strategy.data.active}>
              {plan.isPending ? "Planning…" : "Plan the next 30 days"}
            </Button>
          ) : null
        }
      />
      <GrowthNav />
      {plan.data ? <Notice kind="good" title="Calendar planned" body={plan.data.detail} /> : null}
      {plan.isError ? <ErrorState message={failure(plan.error, "The calendar was not planned.")} /> : null}
      <div className="grid gap-6 xl:grid-cols-2">
        <StrategyEditor view={strategy.data} accounts={accounts.data ?? []} facts={brand.data?.facts ?? []} onChanged={refresh} />
        <EventsPanel events={strategy.data.events} facts={brand.data?.facts ?? []} onChanged={refresh} />
      </div>
      <div className="mt-6">
        <Panel title={`Calendar (${items.length})`} extra={<span className="text-xs text-[var(--muted)]">Times are shown in the time zone of this browser. Read {when(new Date().toISOString())}</span>}>
          {items.length === 0 ? (
            <EmptyState title="Nothing planned" body={strategy.data.active ? "Plan the next 30 days to fill the calendar." : "Approve a strategy first. No calendar is invented."} />
          ) : (
            <CalendarList items={items} onChanged={refresh} />
          )}
        </Panel>
      </div>
    </div>
  );
}
