"use client";

import { Line, Notice, Panel } from "@/components/ds";
import { AccountTags, GrowthNav } from "@/components/growth-ui";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Field, Input, Select } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { when } from "@/lib/format";
import { WEEKDAYS, growth, send, type GrowthAccount } from "@/lib/growth";
import { ApiError } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const EMPTY_FORM = { platform: "facebook", external_id: "", page_id: "", access_token: "", name: "", timezone: "Asia/Kolkata" };

type AccountAction = "verify" | "history" | "insights" | "disconnect";
type Reading = { detail?: string; stored?: number };
type ActionResult = { detail?: string; account?: Reading; media?: Reading };

function failure(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function describe(action: AccountAction, result: ActionResult): string {
  switch (action) {
    case "verify":
    case "history":
      return result.detail ?? "Done.";
    case "insights":
      return `${result.account?.detail ?? ""} Account readings stored: ${result.account?.stored ?? 0}. Post readings stored: ${result.media?.stored ?? 0}.`.trim();
    case "disconnect":
      return "Disconnected. Posts planned for this account are held until it is reconnected.";
    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}

function WindowEditor({ account, onSaved }: { account: GrowthAccount; onSaved: () => void }) {
  const first = account.posting_windows[0] ?? { days: [0, 1, 2, 3, 4], start: "09:00", end: "18:00" };
  const [days, setDays] = useState<number[]>(first.days);
  const [start, setStart] = useState(first.start);
  const [end, setEnd] = useState(first.end);
  const [cap, setCap] = useState(String(account.daily_cap));
  const [zone, setZone] = useState(account.timezone);
  const save = useMutation({
    mutationFn: () => growth<GrowthAccount>(`/accounts/${account.id}`, send({ posting_windows: [{ days, start, end }], daily_cap: Number(cap), timezone: zone }, "PATCH")),
    onSuccess: onSaved,
  });
  return (
    <form
      className="mt-3 space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <div className="flex flex-wrap gap-2" role="group" aria-label="Posting days">
        {WEEKDAYS.map((label, index) => (
          <label key={label} className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={days.includes(index)} onChange={() => setDays((current) => (current.includes(index) ? current.filter((day) => day !== index) : [...current, index].sort()))} />
            {label}
          </label>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Field label="From">
          <Input type="time" value={start} onChange={(event) => setStart(event.target.value)} />
        </Field>
        <Field label="Until">
          <Input type="time" value={end} onChange={(event) => setEnd(event.target.value)} />
        </Field>
        <Field label="Posts per day at most">
          <Input type="number" min={0} max={25} value={cap} onChange={(event) => setCap(event.target.value)} />
        </Field>
        <Field label="Time zone">
          <Input value={zone} onChange={(event) => setZone(event.target.value)} />
        </Field>
      </div>
      <Button type="submit" variant="ghost" disabled={save.isPending}>
        Save window
      </Button>
      {save.isError ? <ErrorState message={failure(save.error, "The window was not saved.")} /> : null}
    </form>
  );
}

export default function GrowthAccountsPage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const accounts = useQuery({ queryKey: ["growth-accounts"], queryFn: () => growth<GrowthAccount[]>("/accounts"), enabled: can("social_growth.read") });
  const [form, setForm] = useState(EMPTY_FORM);
  const [fixtureName, setFixtureName] = useState("");
  const [fixturePlatform, setFixturePlatform] = useState("instagram");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["growth-accounts"] });
    void client.invalidateQueries({ queryKey: ["growth-overview"] });
  };
  const connect = useMutation({
    mutationFn: () => growth<{ detail: string }>("/accounts", send(form)),
    onSuccess: () => {
      setForm(EMPTY_FORM);
      refresh();
    },
  });
  const fixture = useMutation({ mutationFn: () => growth<{ detail: string }>("/accounts/fixture", send({ platform: fixturePlatform, name: fixtureName })), onSuccess: refresh });
  const action = useMutation({
    mutationFn: async ({ id, path }: { id: string; path: AccountAction }) => {
      const result = await growth<ActionResult>(`/accounts/${id}/${path}`, { method: "POST" });
      return { id, detail: describe(path, result) };
    },
    onSuccess: ({ id, detail }) => {
      setNotes((current) => ({ ...current, [id]: detail }));
      refresh();
    },
    onError: (error, variables) => setNotes((current) => ({ ...current, [variables.id]: failure(error, "The request failed.") })),
  });
  if (!can("social_growth.read")) return <DeniedState />;
  if (accounts.isLoading) return <LoadingState label="Reading accounts" />;
  if (accounts.isError) return <ErrorState message={failure(accounts.error, "Accounts could not be loaded.")} />;
  const rows = accounts.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Social growth"
        title="Connected accounts"
        subtitle="Each Facebook Page and Instagram professional account is managed on its own, with its own token, posting window, and daily cap. Tokens are stored encrypted and never shown again."
      />
      <GrowthNav />
      {rows.length === 0 ? (
        <EmptyState title="No accounts connected" body="Connect a Page token below, or add a fixture account to rehearse the workflow. A fixture account never reaches Meta." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {rows.map((account) => (
            <Panel
              key={account.id}
              title={`${account.platform === "instagram" ? "Instagram" : "Facebook"} · ${account.name || account.username || account.external_id}`}
              extra={<AccountTags provenance={account.provenance} status={account.status} />}
            >
              {account.problem ? <Notice kind="warn" title="Action needed" body={account.problem} /> : null}
              <Line label="Account id" value={account.external_id} />
              {account.platform === "instagram" ? <Line label="Linked Page" value={account.page_id || "—"} /> : null}
              <Line label="Token expires" value={account.token_expires_at ? when(account.token_expires_at) : "Unknown until verified"} />
              <Line label="Data access expires" value={account.data_access_expires_at ? when(account.data_access_expires_at) : "Unknown until verified"} />
              <Line label="Granted permissions" value={account.granted_scopes.length ? account.granted_scopes.join(", ") : account.capabilities.checked ? "None returned" : "Not checked"} />
              <Line label="Missing permissions" value={account.missing_scopes.length ? account.missing_scopes.join(", ") : account.capabilities.checked ? "None" : "Not checked"} />
              <Line label="Publishing eligibility" value={account.publish_eligible ? "Eligible from the last stored check" : "Not eligible"} />
              <Line label="Insight eligibility" value={account.insights_eligible ? "Eligible from the last stored check" : "Not eligible"} />
              <Line label="Posting limit" value={account.posting_limit} />
              <Line label="Reconnect" value={account.reconnect_required ? "Reconnect this account before any provider call." : "No reconnection is required from the stored token state."} />
              {account.last_error ? <Line label="Connection error" value={account.last_error} /> : null}
              <Line label="Followers" value={account.followers_count === null ? "Unavailable" : `${account.followers_count.toLocaleString()} (read ${when(account.followers_observed_at)})`} />
              <Line label="Graph version" value={account.api_version || "—"} />
              <Line label="Window" value={account.posting_windows.map((window) => `${window.days.map((day) => WEEKDAYS[day]).join(" ")} ${window.start}-${window.end}`).join("; ")} />
              <Line label="Daily cap" value={String(account.daily_cap)} />
              {can("social_growth.write") ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button type="button" variant="ghost" onClick={() => action.mutate({ id: account.id, path: "verify" })} disabled={action.isPending}>
                    Verify
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => action.mutate({ id: account.id, path: "history" })} disabled={action.isPending}>
                    Read past posts
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => action.mutate({ id: account.id, path: "insights" })} disabled={action.isPending}>
                    Read insights
                  </Button>
                  {can("integrations.write") && account.status !== "disconnected" ? (
                    <Button type="button" variant="ghost" onClick={() => action.mutate({ id: account.id, path: "disconnect" })} disabled={action.isPending}>
                      Disconnect
                    </Button>
                  ) : null}
                </div>
              ) : null}
              {notes[account.id] ? <p className="mt-2 text-sm text-[var(--muted)]">{notes[account.id]}</p> : null}
              {can("social_growth.write") ? <WindowEditor account={account} onSaved={refresh} /> : null}
            </Panel>
          ))}
        </div>
      )}
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {can("integrations.write") && can("social_growth.write") ? (
          <Panel title="Connect a Page or Instagram account">
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                connect.mutate();
              }}
            >
              <Field label="Platform">
                <Select value={form.platform} onChange={(event) => setForm({ ...form, platform: event.target.value })}>
                  <option value="facebook">Facebook Page</option>
                  <option value="instagram">Instagram professional account</option>
                </Select>
              </Field>
              <Field label={form.platform === "instagram" ? "Instagram account id" : "Page id"}>
                <Input value={form.external_id} onChange={(event) => setForm({ ...form, external_id: event.target.value })} inputMode="numeric" required />
              </Field>
              {form.platform === "instagram" ? (
                <Field label="Linked Facebook Page id">
                  <Input value={form.page_id} onChange={(event) => setForm({ ...form, page_id: event.target.value })} inputMode="numeric" required />
                </Field>
              ) : null}
              <Field label="Page access token">
                <Input type="password" autoComplete="off" value={form.access_token} onChange={(event) => setForm({ ...form, access_token: event.target.value })} required />
              </Field>
              <Field label="Display name">
                <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
              </Field>
              <Field label="Time zone">
                <Input value={form.timezone} onChange={(event) => setForm({ ...form, timezone: event.target.value })} />
              </Field>
              <Button type="submit" disabled={connect.isPending}>
                Save encrypted
              </Button>
              {connect.data ? <p className="text-sm text-[var(--muted)]">{connect.data.detail}</p> : null}
              {connect.isError ? <ErrorState message={failure(connect.error, "The account was not saved.")} /> : null}
            </form>
          </Panel>
        ) : (
          <Panel title="Connect an account">
            <p className="text-sm text-[var(--muted)]">Connecting a token needs integrations.write and social_growth.write.</p>
          </Panel>
        )}
        {can("social_growth.write") ? (
          <Panel title="Fixture account for rehearsal">
            <p className="mb-3 text-sm text-[var(--muted)]">A fixture account lets the calendar and creative run without Meta. It cannot publish, and anything measured on it is labeled fixture.</p>
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Platform">
                <Select value={fixturePlatform} onChange={(event) => setFixturePlatform(event.target.value)}>
                  <option value="instagram">Instagram</option>
                  <option value="facebook">Facebook</option>
                </Select>
              </Field>
              <Field label="Name">
                <Input value={fixtureName} onChange={(event) => setFixtureName(event.target.value)} placeholder="Rehearsal account" />
              </Field>
              <Button type="button" variant="ghost" onClick={() => fixture.mutate()} disabled={fixture.isPending}>
                Add fixture account
              </Button>
            </div>
            {fixture.isError ? <ErrorState message={failure(fixture.error, "The fixture account was not created.")} /> : null}
          </Panel>
        ) : null}
      </div>
    </div>
  );
}
