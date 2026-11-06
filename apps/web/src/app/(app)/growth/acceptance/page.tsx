"use client";

import { Line, Notice, Panel } from "@/components/ds";
import { GrowthNav } from "@/components/growth-ui";
import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { Button, Field, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { when } from "@/lib/format";
import { growth, send, type AcceptanceStep } from "@/lib/growth";
import { ApiError } from "@agrayian/sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

function failure(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function statusLabel(status: AcceptanceStep["status"]): string {
  switch (status) {
    case "not_started":
      return "Not started";
    case "blocked":
      return "Blocked by configuration";
    case "awaiting_authorization":
      return "Awaiting authorization";
    case "verified_live":
      return "Verified with real provider";
    case "failed":
      return "Failed";
    case "not_supported":
      return "Not supported";
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}

export default function GrowthAcceptancePage() {
  const { can } = useAuth();
  const client = useQueryClient();
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<Record<string, string>>({});
  const steps = useQuery({
    queryKey: ["growth-acceptance"],
    queryFn: () => growth<AcceptanceStep[]>("/acceptance"),
    enabled: can("social_growth.read"),
  });
  const authorize = useMutation({
    mutationFn: ({ step, note }: { step: string; note: string }) => growth<AcceptanceStep>(`/acceptance/${step}/authorize`, send({ note })),
    onSuccess: (step) => {
      setMessages((current) => ({ ...current, [step.step_key]: "Authorization recorded. No provider was contacted." }));
      void client.invalidateQueries({ queryKey: ["growth-acceptance"] });
    },
    onError: (error, variables) => setMessages((current) => ({ ...current, [variables.step]: failure(error, "The authorization was not recorded.") })),
  });
  if (!can("social_growth.read")) return <DeniedState />;
  if (steps.isLoading) return <LoadingState label="Reading the acceptance checklist" />;
  if (steps.isError) return <ErrorState message={failure(steps.error, "The acceptance checklist could not be loaded.")} />;
  const rows = steps.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Social growth"
        title="Live acceptance"
        subtitle="Each step stays unverified until a person authorizes it and a real provider result is stored. Authorizing a step does not call Meta or Google, and a fixture result is never marked live-verified."
      />
      <GrowthNav />
      <Notice
        kind="warn"
        title="External actions stay off"
        body="Publishing, insights, and GA4 remain disabled until this deployment is configured for them and the matching step is authorized. This page does not send a post, an advertisement, an email, or a message."
      />
      <div className="mt-4 grid gap-4">
        {rows.map((step) => (
          <Panel key={step.step_key} title={step.title} extra={<span className="text-xs font-semibold text-[var(--meta)]">{statusLabel(step.status)}</span>}>
            <Line label="State" value={statusLabel(step.status)} />
            <Line label="Detail" value={step.reason || "—"} />
            <Line label="Authorized" value={step.authorized_at ? when(step.authorized_at) : "Not authorized"} />
            {step.note ? <Line label="Note" value={step.note} /> : null}
            {can("social_growth.approve") && step.status !== "verified_live" && step.status !== "not_supported" ? (
              <form
                className="mt-3 grid gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  authorize.mutate({ step: step.step_key, note: notes[step.step_key] ?? "" });
                }}
              >
                <Field label="Authorization note">
                  <Input value={notes[step.step_key] ?? ""} onChange={(event) => setNotes((current) => ({ ...current, [step.step_key]: event.target.value }))} />
                </Field>
                <Button type="submit" disabled={authorize.isPending}>
                  Authorize this step
                </Button>
              </form>
            ) : null}
            {messages[step.step_key] ? <p className="mt-2 text-sm text-[var(--muted)]">{messages[step.step_key]}</p> : null}
          </Panel>
        ))}
      </div>
    </div>
  );
}
