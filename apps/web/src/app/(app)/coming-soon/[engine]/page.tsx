"use client";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/states";
import Link from "next/link";
import { useParams } from "next/navigation";

const COPY: Record<string, { title: string; eyebrow: string; body: string }> = {
  market: {
    eyebrow: "Moved",
    title: "Market Intelligence is live",
    body: "Open /market for scored theses, signals, and triggers. This alias remains so old links do not invent KPIs.",
  },
  acquisition: {
    eyebrow: "Moved",
    title: "Acquisition is live",
    body: "Open /acquisition for inbound capture and dedupe review. Sequences and paid ads are still later.",
  },
  success: {
    eyebrow: "Moved",
    title: "Success is live",
    body: "Open /success for health, onboarding, and the customer desk. Renewals, expansion, and advocacy have their own rooms.",
  },
};

export default function ComingSoonPage() {
  const params = useParams<{ engine: string }>();
  const copy = COPY[params.engine] ?? {
    eyebrow: "Later engine",
    title: "Not yet built",
    body: "This surface is reserved. Unfinished engines do not invent KPIs.",
  };
  return (
    <div>
      <PageHeader eyebrow={copy.eyebrow} title={copy.title} subtitle="Designed empty on purpose." />
      <EmptyState
        title="Use the live desk"
        body={copy.body}
        action={
          params.engine === "market" ? (
            <Link href="/market" className="text-brand">Open Market Intelligence</Link>
          ) : params.engine === "acquisition" ? (
            <Link href="/acquisition" className="text-brand">Open Acquisition</Link>
          ) : params.engine === "success" ? (
            <Link href="/success" className="text-brand">Open Success</Link>
          ) : null
        }
      />
    </div>
  );
}
