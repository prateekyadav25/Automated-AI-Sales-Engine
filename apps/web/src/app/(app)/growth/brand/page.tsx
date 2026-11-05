"use client";

import { Line, Notice, Panel } from "@/components/ds";
import { Cell, GrowthNav, GrowthTable, ProvenanceTag, StatusTag } from "@/components/growth-ui";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, CheckField, Field, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { when } from "@/lib/format";
import { growth, send, type BrandFact, type BrandView } from "@/lib/growth";
import { ApiError } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

const CATEGORIES = ["company_name", "description", "product", "service", "location", "contact", "social_profile", "claim", "theme", "voice", "color"];

function message(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

export default function BrandIntelligencePage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const brand = useQuery({ queryKey: ["growth-brand"], queryFn: () => growth<BrandView>("/brand"), enabled: can("social_growth.read") });
  const [website, setWebsite] = useState("");
  const [ga4, setGa4] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [filter, setFilter] = useState("all");
  const [factForm, setFactForm] = useState({ category: "claim", statement: "", source_url: "", evidence: "", approve: false });
  const [usernames, setUsernames] = useState("");
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["growth-brand"] });
    void client.invalidateQueries({ queryKey: ["growth-overview"] });
  };
  const analyze = useMutation({
    mutationFn: () => growth<{ status: string; detail: string }>("/brand/analyze", send({ website_url: website || brand.data?.profile?.website_url || "" })),
    onSuccess: refresh,
  });
  const settings = useMutation({
    mutationFn: () => growth<BrandView>("/brand/settings", send({ website_url: website || null, ga4_property_id: ga4 || null }, "PUT")),
    onSuccess: refresh,
  });
  const review = useMutation({
    mutationFn: (decision: string) => growth<{ updated: number; detail: string }>("/brand/facts/review", send({ fact_ids: selected, decision, note })),
    onSuccess: () => {
      setSelected([]);
      setNote("");
      refresh();
    },
  });
  const addFact = useMutation({
    mutationFn: () => growth<{ status: string; detail?: string }>("/brand/facts", send(factForm)),
    onSuccess: () => {
      setFactForm({ category: "claim", statement: "", source_url: "", evidence: "", approve: false });
      refresh();
    },
  });
  const competitors = useMutation({
    mutationFn: (refreshNow: boolean) => growth<{ status: string; detail: string }>("/brand/competitors", send({ usernames: usernames.split(/[\s,]+/).filter(Boolean), refresh: refreshNow })),
    onSuccess: refresh,
  });
  const facts = useMemo(() => (brand.data?.facts ?? []).filter((fact) => filter === "all" || fact.category === filter || fact.state === filter), [brand.data, filter]);
  if (!can("social_growth.read")) return <DeniedState />;
  if (brand.isLoading) return <LoadingState label="Reading brand facts" />;
  if (brand.isError || !brand.data) return <ErrorState message={message(brand.error, "Brand facts could not be loaded.")} />;
  const view = brand.data;
  const profile = view.profile;
  const analysis = (profile?.analysis ?? {}) as Record<string, unknown>;
  const voice = (profile?.voice ?? {}) as Record<string, unknown>;
  const toggle = (fact: BrandFact) => setSelected((current) => (current.includes(fact.id) ? current.filter((id) => id !== fact.id) : [...current, fact.id]));
  return (
    <div>
      <PageHeader
        eyebrow="Social growth"
        title="Brand intelligence"
        subtitle="Facts read from the company's own website and authorized accounts. Each fact keeps its page, the evidence, and the time it was read. Only approved facts reach copy, and claims always wait for a person."
      />
      <GrowthNav />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Website and analytics">
          {can("social_growth.write") ? (
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                analyze.mutate();
              }}
            >
              <Field label="Company website">
                <Input placeholder={profile?.website_url || "https://example.com"} value={website} onChange={(event) => setWebsite(event.target.value)} />
              </Field>
              <Field label="GA4 property id (optional)">
                <Input placeholder="123456789" value={ga4} onChange={(event) => setGa4(event.target.value)} inputMode="numeric" />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={analyze.isPending}>
                  {analyze.isPending ? "Reading the site…" : "Analyze website"}
                </Button>
                <Button type="button" variant="ghost" disabled={settings.isPending} onClick={() => settings.mutate()}>
                  Save settings
                </Button>
              </div>
              {analyze.data ? <Notice kind={analyze.data.status === "analyzed" ? "good" : "warn"} title={`Analysis ${analyze.data.status}`} body={analyze.data.detail} /> : null}
              {analyze.isError ? <ErrorState message={message(analyze.error, "The website could not be read.")} /> : null}
              {settings.isError ? <ErrorState message={message(settings.error, "Settings were not saved.")} /> : null}
            </form>
          ) : (
            <p className="text-sm text-[var(--muted)]">You can view the analysis. Running it needs social_growth.write.</p>
          )}
          {profile ? (
            <div className="mt-4">
              <Line label="Company" value={profile.company_name || "Not found"} />
              <Line label="Status" value={<StatusTag status={view.status} />} />
              <Line label="Last read" value={when(profile.last_analysis_at)} />
              <Line label="Pages read" value={`${analysis.pages_fetched ?? 0} read · ${analysis.pages_failed ?? 0} unreadable · ${analysis.pages_disallowed ?? 0} disallowed by robots.txt`} />
              <Line label="Method" value={String(analysis.method ?? "—")} />
            </div>
          ) : null}
        </Panel>
        <Panel title="Look and voice">
          {!profile ? (
            <p className="text-sm text-[var(--muted)]">Nothing is measured until the site is read.</p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                {profile.logo ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={profile.logo.preview_url} alt="Logo read from the website" className="h-14 w-auto rounded bg-white p-1" />
                ) : (
                  <span className="text-sm text-[var(--muted)]">No logo was found on the site.</span>
                )}
                {profile.palette.map((swatch) => (
                  <span key={swatch.hex} className="flex items-center gap-1 text-xs" title={`From the ${swatch.source}`}>
                    <span className="inline-block h-6 w-6 rounded border border-[var(--line)]" style={{ background: swatch.hex }} />
                    {swatch.hex}
                  </span>
                ))}
              </div>
              <p className="text-xs text-[var(--muted)]">Templates use approved colour facts only. Approve a colour below to use it.</p>
              <Line label="Sentences measured" value={String(voice.sentences ?? 0)} />
              <Line label="Average sentence length" value={voice.average_sentence_words ? `${voice.average_sentence_words} words` : "—"} />
              <Line label="Sentences that address the reader" value={typeof voice.second_person_share === "number" ? `${Math.round((voice.second_person_share as number) * 100)}%` : "—"} />
              <Line label="Reading ease (Flesch)" value={String(voice.reading_ease ?? "—")} />
            </div>
          )}
        </Panel>
      </div>
      <div className="mt-6">
        <Panel title={`Facts (${view.facts.length})`} extra={<Select value={filter} onChange={(event) => setFilter(event.target.value)} aria-label="Filter facts">
          <option value="all">All</option>
          <option value="needs_review">Needs review</option>
          <option value="extracted">Extracted</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          {CATEGORIES.map((category) => (
            <option key={category} value={category}>
              {category.replaceAll("_", " ")}
            </option>
          ))}
        </Select>}>
          {view.facts.length === 0 ? (
            <EmptyState title="No facts" body="Analyze the website or record a fact with its source. Nothing is invented." />
          ) : (
            <>
              {can("social_growth.approve") ? (
                <div className="mb-3 flex flex-wrap items-end gap-2">
                  <Field label="Review note">
                    <Input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Why this decision" />
                  </Field>
                  <Button type="button" disabled={!selected.length || review.isPending} onClick={() => review.mutate("approve")}>
                    Approve {selected.length || ""}
                  </Button>
                  <Button type="button" variant="ghost" disabled={!selected.length || review.isPending} onClick={() => review.mutate("reject")}>
                    Reject
                  </Button>
                  {review.data ? <span className="text-sm text-[var(--muted)]">{review.data.detail}</span> : null}
                </div>
              ) : null}
              <GrowthTable head={["", "Category", "Statement", "Source and evidence", "State"]}>
                {facts.map((fact) => (
                  <tr key={fact.id}>
                    <Cell>
                      {can("social_growth.approve") ? <input type="checkbox" aria-label={`Select ${fact.statement}`} checked={selected.includes(fact.id)} onChange={() => toggle(fact)} /> : null}
                    </Cell>
                    <Cell className="whitespace-nowrap text-xs uppercase tracking-[0.1em]">{fact.category.replaceAll("_", " ")}</Cell>
                    <Cell className="max-w-md">
                      {fact.category === "color" && fact.value.startsWith("#") ? <span className="mr-2 inline-block h-3 w-3 rounded" style={{ background: fact.value }} /> : null}
                      {fact.statement}
                    </Cell>
                    <Cell className="max-w-sm text-xs text-[var(--muted)]">
                      {fact.source_url.startsWith("http") ? (
                        <a className="break-all text-brand" href={fact.source_url} target="_blank" rel="noreferrer">
                          {fact.source_url}
                        </a>
                      ) : (
                        fact.source_url
                      )}
                      <div>{fact.evidence !== fact.statement ? fact.evidence : ""}</div>
                      <div>
                        {fact.method} · read {when(fact.observed_at)}
                      </div>
                    </Cell>
                    <Cell>
                      <StatusTag status={fact.state} />
                    </Cell>
                  </tr>
                ))}
              </GrowthTable>
            </>
          )}
        </Panel>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {can("social_growth.write") ? (
          <Panel title="Record a fact with its source">
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                addFact.mutate();
              }}
            >
              <Field label="Category">
                <Select value={factForm.category} onChange={(event) => setFactForm({ ...factForm, category: event.target.value })}>
                  {CATEGORIES.map((category) => (
                    <option key={category} value={category}>
                      {category.replaceAll("_", " ")}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Statement">
                <Textarea rows={2} value={factForm.statement} onChange={(event) => setFactForm({ ...factForm, statement: event.target.value })} required />
              </Field>
              <Field label="Source address">
                <Input value={factForm.source_url} onChange={(event) => setFactForm({ ...factForm, source_url: event.target.value })} placeholder="https://" />
              </Field>
              <Field label="Evidence">
                <Textarea rows={2} value={factForm.evidence} onChange={(event) => setFactForm({ ...factForm, evidence: event.target.value })} />
              </Field>
              {can("social_growth.approve") ? <CheckField label="Approve now" checked={factForm.approve} onChange={(event) => setFactForm({ ...factForm, approve: event.target.checked })} /> : null}
              <Button type="submit" disabled={addFact.isPending || !factForm.statement.trim()}>
                Save fact
              </Button>
              {addFact.data?.detail ? <p className="text-sm text-[var(--muted)]">{addFact.data.detail}</p> : null}
              {addFact.isError ? <ErrorState message={message(addFact.error, "The fact was not saved.")} /> : null}
            </form>
          </Panel>
        ) : null}
        <Panel title="Competitor benchmarks">
          <p className="mb-3 text-sm text-[var(--muted)]">Figures come only from Instagram Business Discovery through a connected account. Hidden counts stay empty.</p>
          {can("social_growth.write") ? (
            <div className="mb-3 flex flex-wrap items-end gap-2">
              <Field label="Instagram usernames">
                <Input value={usernames} onChange={(event) => setUsernames(event.target.value)} placeholder={(profile?.competitor_usernames ?? []).join(", ") || "brand_one, brand_two"} />
              </Field>
              <Button type="button" variant="ghost" onClick={() => competitors.mutate(false)} disabled={competitors.isPending}>
                Save
              </Button>
              <Button type="button" onClick={() => competitors.mutate(true)} disabled={competitors.isPending}>
                Refresh figures
              </Button>
            </div>
          ) : null}
          {competitors.data ? <p className="mb-2 text-sm text-[var(--muted)]">{competitors.data.detail}</p> : null}
          {view.competitors.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No competitor is saved.</p>
          ) : (
            <GrowthTable head={["Account", "Followers", "Posts per week", "Average likes", "Read"]}>
              {view.competitors.map((row) => (
                <tr key={row.id}>
                  <Cell>@{row.username}</Cell>
                  <Cell>{row.followers_count ?? "Unavailable"}</Cell>
                  <Cell>{row.posts_per_week ?? "Unavailable"}</Cell>
                  <Cell>{row.avg_likes ?? "Unavailable"}</Cell>
                  <Cell className="text-xs text-[var(--muted)]">
                    <StatusTag status={row.status} /> {row.retrieved_at ? when(row.retrieved_at) : "Not read"} {row.error}
                  </Cell>
                </tr>
              ))}
            </GrowthTable>
          )}
        </Panel>
      </div>
      <div className="mt-6">
        <Panel title="Sources">
          {view.sources.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No source has been read.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {view.sources.map((source) => (
                <li key={source.id} className="flex flex-wrap items-center gap-2">
                  <StatusTag status={source.status === "fetched" ? "recorded" : source.status} />
                  <span className="text-xs uppercase tracking-[0.1em] text-[var(--muted)]">{source.kind.replaceAll("_", " ")}</span>
                  <span className="break-all">{source.url}</span>
                  <span className="text-xs text-[var(--muted)]">
                    {source.http_status ? `HTTP ${source.http_status} · ` : ""}
                    {when(source.fetched_at)}
                  </span>
                  <ProvenanceTag value={source.provenance} />
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
