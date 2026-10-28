"use client";

import { MeetingBooking } from "@/components/meeting-booking";
import { PageHeader } from "@/components/page-header";
import { DeniedState, ErrorState, LoadingState } from "@/components/states";
import { Button, Field, Textarea } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { Meeting } from "@/lib/types";
import { api } from "@agrayian/sdk";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";

export default function MeetingOutcomePage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const [summary, setSummary] = useState("");
  const [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: ["meetings"],
    queryFn: async () => (await api<Meeting[]>("/api/v1/lifecycle/meetings")).data ?? [],
    enabled: can("meetings.read"),
  });
  const qualify = useMutation({
    mutationFn: (qualified: boolean) =>
      api<{ qualified: boolean; opportunity_id: string | null }>(`/api/v1/workflow/meetings/${params.id}/outcome`, {
        method: "POST",
        body: JSON.stringify({ qualified, summary }),
      }),
    onSuccess: (result) => {
      const opportunity = result.data?.opportunity_id;
      setNotice(opportunity ? `Qualified. Opportunity ${opportunity} was recorded.` : "Not qualified. No opportunity was created.");
    },
    onError: (error: Error) => setNotice(error.message),
  });
  if (!can("meetings.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState label="Opening the meeting" />;
  if (query.isError) return <ErrorState message="Meetings could not be loaded." />;
  const meeting = (query.data ?? []).find((row) => row.id === params.id);
  if (!meeting) return <ErrorState message="This meeting is not in the tenant." />;
  return (
    <div>
      <PageHeader
        eyebrow="Sales"
        title={meeting.title}
        subtitle="A booking is not attendance. A meeting becomes an opportunity only when it is marked qualified. The summary is the evidence."
        nextHref="/pipeline"
        nextLabel="Pipeline"
      />
      <div className="panel mb-4 p-5 text-sm">
        <MeetingBooking meeting={meeting} />
      </div>
      <div className="panel mb-4 p-5 text-sm text-[var(--muted)]">
        <p>{meeting.summary || "No recap recorded."}</p>
        <p className="mt-2">{meeting.next_steps || "No next step recorded."}</p>
      </div>
      {can("opportunities.write") ? (
        <form className="panel max-w-2xl space-y-4 p-5" onSubmit={(event) => event.preventDefault()}>
          <Field label="Outcome summary">
            <Textarea rows={5} value={summary} onChange={(event) => setSummary(event.target.value)} />
          </Field>
          <div className="flex gap-2">
            <Button onClick={() => qualify.mutate(true)} disabled={qualify.isPending}>Qualified</Button>
            <Button variant="line" onClick={() => qualify.mutate(false)} disabled={qualify.isPending}>Not qualified</Button>
          </div>
          {notice ? <p className="text-sm text-[var(--muted)]">{notice}</p> : null}
        </form>
      ) : null}
    </div>
  );
}
