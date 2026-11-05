"use client";

import { Line, Notice, Panel } from "@/components/ds";
import { AssetPreview, CheckList, GrowthNav, ProvenanceTag, StatusTag } from "@/components/growth-ui";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Field, Input, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { when } from "@/lib/format";
import { growth, provenanceLabel, send, type Creative, type Grant } from "@/lib/growth";
import { ApiError } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

function failure(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function CreativeCard({ creative, onChanged }: { creative: Creative; onChanged: () => void }) {
  const { can } = useAuth();
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [caption, setCaption] = useState(creative.caption);
  const [tags, setTags] = useState(creative.hashtags.join(" "));
  const review = useMutation({ mutationFn: (decision: string) => growth<Creative>(`/creatives/${creative.id}/review`, send({ decision, note })), onSuccess: onChanged });
  const revise = useMutation({
    mutationFn: () => growth<Creative>(`/creatives/${creative.id}`, send({ caption, hashtags: tags.split(/[\s,]+/).filter(Boolean) }, "PATCH")),
    onSuccess: () => {
      setEditing(false);
      onChanged();
    },
  });
  const unsupported = creative.claims.unsupported ?? [];
  const sensitive = creative.claims.sensitive ?? [];
  return (
    <Panel
      title={`${creative.account?.platform === "instagram" ? "Instagram" : "Facebook"} ${creative.format} · ${creative.account?.name ?? ""} · v${creative.version}`}
      extra={
        <span className="flex flex-wrap gap-2">
          {creative.account ? <ProvenanceTag value={creative.account.provenance} /> : null}
          <StatusTag status={creative.status} />
          <StatusTag status={creative.quality_state} />
        </span>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          {creative.assets.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">{creative.format === "text" ? "A text post with a link. The copy is the preview." : "No asset was rendered. See the quality report."}</p>
          ) : (
            <div className="flex flex-wrap gap-3">
              {creative.assets.map((asset) => (
                <AssetPreview key={asset.id} asset={asset} />
              ))}
            </div>
          )}
        </div>
        <div className="space-y-3 text-sm">
          <Line label="Planned" value={when(creative.planned_for)} />
          <Line label="Written by" value={creative.generation === "model" ? `Model ${creative.model_id}` : provenanceLabel(creative.generation)} />
          {editing ? (
            <form
              className="space-y-2"
              onSubmit={(event) => {
                event.preventDefault();
                revise.mutate();
              }}
            >
              <Field label="Caption">
                <Textarea rows={8} value={caption} onChange={(event) => setCaption(event.target.value)} />
              </Field>
              <Field label="Hashtags">
                <Input value={tags} onChange={(event) => setTags(event.target.value)} />
              </Field>
              <div className="flex gap-2">
                <Button type="submit" disabled={revise.isPending}>
                  Save as new version
                </Button>
                <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </div>
              {revise.isError ? <ErrorState message={failure(revise.error, "The edit was not saved.")} /> : null}
            </form>
          ) : (
            <div className="whitespace-pre-wrap rounded-md border border-[var(--line)] bg-[#101722] p-3">
              {creative.caption}
              {creative.hashtags.length ? `\n\n${creative.hashtags.map((tag) => `#${tag}`).join(" ")}` : ""}
            </div>
          )}
          <p className="text-xs text-[var(--muted)]">Alt text: {creative.alt_text}</p>
          {unsupported.length ? <Notice kind="warn" title="Unsupported claims" body={`${unsupported.join(", ")}. No approved fact states these. Remove them, or approve with a note that names the evidence.`} /> : null}
          {sensitive.length ? <Notice kind="warn" title="Sensitive terms" body={`${sensitive.join(", ")}. The strategy says these always need a person.`} /> : null}
          {creative.review_reasons.length ? (
            <ul className="list-disc space-y-1 pl-5 text-xs text-[var(--muted)]">
              {creative.review_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
          <div>
            <p className="text-xs font-medium text-navy">Caption checks</p>
            <CheckList checks={creative.quality.caption?.checks} />
          </div>
          <div>
            <p className="text-xs font-medium text-navy">Facts used</p>
            <ul className="space-y-1 text-xs text-[var(--muted)]">
              {(creative.brief.facts ?? []).filter((fact) => creative.fact_ids.includes(fact.id)).map((fact) => (
                <li key={fact.id}>
                  {fact.statement}{" "}
                  <a className="text-brand" href={fact.source_url} target="_blank" rel="noreferrer">
                    source
                  </a>
                </li>
              ))}
            </ul>
          </div>
          {creative.assets.map((asset) => (
            <details key={`checks-${asset.id}`} className="text-xs">
              <summary className="cursor-pointer text-[var(--muted)]">
                Checks for {asset.role} {asset.position + 1}
              </summary>
              <CheckList checks={asset.quality.checks} />
            </details>
          ))}
          {creative.status === "approved" ? <p className="text-xs text-[var(--muted)]">{creative.review_note || "Approved."}</p> : null}
          {["draft", "needs_review"].includes(creative.status) ? (
            <div className="space-y-2">
              {can("social_growth.approve") ? (
                <>
                  <Field label="Review note">
                    <Input value={note} onChange={(event) => setNote(event.target.value)} placeholder={unsupported.length ? "Name the evidence for each claim" : "Optional"} />
                  </Field>
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" disabled={review.isPending || creative.quality_state !== "passed"} onClick={() => review.mutate("approve")}>
                      Approve creative
                    </Button>
                    <Button type="button" variant="ghost" disabled={review.isPending} onClick={() => review.mutate("reject")}>
                      Reject
                    </Button>
                  </div>
                </>
              ) : null}
              {can("social_growth.write") && !editing ? (
                <Button type="button" variant="ghost" onClick={() => setEditing(true)}>
                  Edit caption
                </Button>
              ) : null}
              {review.isError ? <ErrorState message={failure(review.error, "The decision was not saved.")} /> : null}
            </div>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}

function GrantsPanel() {
  const { can } = useAuth();
  const client = useQueryClient();
  const grants = useQuery({ queryKey: ["growth-grants"], queryFn: () => growth<Grant[]>("/grants"), enabled: can("social_growth.read") });
  const [platform, setPlatform] = useState("instagram");
  const [cap, setCap] = useState("2");
  const [days, setDays] = useState("14");
  const create = useMutation({ mutationFn: () => growth<Grant[]>("/grants", send({ platform, volume_cap: Number(cap), days: Number(days) })), onSuccess: () => void client.invalidateQueries({ queryKey: ["growth-grants"] }) });
  const revoke = useMutation({ mutationFn: (id: string) => growth<Grant[]>(`/grants/${id}/revoke`, { method: "POST" }), onSuccess: () => void client.invalidateQueries({ queryKey: ["growth-grants"] }) });
  return (
    <Panel title="Execution grants">
      <p className="mb-3 text-sm text-[var(--muted)]">
        A grant lets approved creative publish without a per-post approval, for one platform, up to a daily number of posts, until it expires. Without a grant every post waits in the decision inbox. Publishing also needs the live deployment mode and an authorized workspace.
      </p>
      {grants.isError ? <ErrorState message="Grants could not be loaded." /> : null}
      {(grants.data ?? []).length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No grant exists.</p>
      ) : (
        <ul className="mb-3 space-y-2 text-sm">
          {(grants.data ?? []).map((grant) => (
            <li key={grant.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {grant.platform} · up to {grant.volume_cap} a day · expires {when(grant.expires_at)} · {grant.published_last_24h} in the last 24 hours
              </span>
              <span className="flex gap-2">
                <StatusTag status={grant.status} />
                {can("social_growth.approve") && grant.status === "active" ? (
                  <Button type="button" variant="ghost" onClick={() => revoke.mutate(grant.id)}>
                    Revoke
                  </Button>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
      {can("social_growth.approve") ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Platform">
            <Select value={platform} onChange={(event) => setPlatform(event.target.value)}>
              <option value="instagram">Instagram</option>
              <option value="facebook">Facebook</option>
            </Select>
          </Field>
          <Field label="Posts per day">
            <Input type="number" min={1} max={25} value={cap} onChange={(event) => setCap(event.target.value)} />
          </Field>
          <Field label="Days">
            <Input type="number" min={1} max={90} value={days} onChange={(event) => setDays(event.target.value)} />
          </Field>
          <Button type="button" variant="ghost" onClick={() => create.mutate()} disabled={create.isPending}>
            Create grant
          </Button>
          {create.isError ? <ErrorState message={failure(create.error, "The grant was not created.")} /> : null}
        </div>
      ) : null}
    </Panel>
  );
}

export default function CreativeStudioPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const queue = useQuery({ queryKey: ["growth-review"], queryFn: () => growth<Creative[]>("/creatives/review"), enabled: can("social_growth.read") });
  const refresh = () => {
    for (const key of ["growth-review", "growth-calendar", "growth-overview"]) void client.invalidateQueries({ queryKey: [key] });
  };
  if (!can("social_growth.read")) return <DeniedState />;
  if (queue.isLoading) return <LoadingState label="Reading the review queue" />;
  if (queue.isError) return <ErrorState message={failure(queue.error, "The review queue could not be loaded.")} />;
  const rows = queue.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Social growth"
        title="Creative studio"
        subtitle="Captions come from approved facts. Images, carousels, and 9:16 Reels are rendered from the brand template and checked before anyone can approve them. Unsupported claims and sensitive terms always come here."
      />
      <GrowthNav />
      <div className="space-y-6">
        {rows.length === 0 ? (
          <EmptyState title="Nothing waiting for review" body="Produce creative from the calendar. Drafts and flagged posts appear here." />
        ) : (
          rows.map((creative) => (
            <div key={creative.id} data-testid="growth-creative" data-creative-id={creative.id}>
              <CreativeCard creative={creative} onChanged={refresh} />
            </div>
          ))
        )}
        <GrantsPanel />
      </div>
    </div>
  );
}
