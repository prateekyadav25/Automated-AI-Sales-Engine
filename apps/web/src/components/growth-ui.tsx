"use client";

import { Notice } from "@/components/ds";
import { Badge } from "@/components/ui";
import { provenanceLabel, statusTone, type GrowthAsset } from "@/lib/growth";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export function GrowthTable({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-[var(--line)] bg-[#101722] text-xs font-semibold text-[var(--meta)]">
          <tr>
            {head.map((label, index) => (
              <th key={`${label}-${index}`} className="px-4 py-2.5">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Cell({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`border-b border-[var(--line)] px-4 py-2.5 align-top ${className}`}>{children}</td>;
}

const TABS = [
  { href: "/growth", label: "Command centre" },
  { href: "/growth/brand", label: "Brand intelligence" },
  { href: "/growth/accounts", label: "Accounts" },
  { href: "/growth/acceptance", label: "Live acceptance" },
  { href: "/growth/calendar", label: "Strategy & calendar" },
  { href: "/growth/studio", label: "Creative studio" },
  { href: "/growth/performance", label: "Performance & leads" },
];

export function GrowthNav() {
  const pathname = usePathname();
  return (
    <nav className="mb-6 flex flex-wrap gap-2" aria-label="Social growth sections">
      {TABS.map((tab) => (
        <Link key={tab.href} href={tab.href} className={pathname === tab.href ? "btn primary" : "btn"} aria-current={pathname === tab.href ? "page" : undefined}>
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}

export function StatusTag({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{status.replaceAll("_", " ")}</Badge>;
}

export function ProvenanceTag({ value }: { value: string }) {
  return <Badge tone={value === "live" ? "ok" : value === "fixture" || value === "mock" ? "blue" : "neutral"}>{provenanceLabel(value)}</Badge>;
}

export function AccountTags({ provenance, status }: { provenance: string; status: string }) {
  return (
    <span className="flex flex-wrap gap-2">
      <ProvenanceTag value={provenance} />
      {status === provenance ? null : <StatusTag status={status} />}
    </span>
  );
}

export function CheckList({ checks }: { checks: { name: string; ok: boolean; detail: string }[] | undefined }) {
  if (!checks?.length) return <p className="text-sm text-[var(--muted)]">No checks ran.</p>;
  return (
    <ul className="space-y-1 text-xs">
      {checks.map((check) => (
        <li key={`${check.name}-${check.detail}`} className="flex gap-2">
          <span className={check.ok ? "text-[#8DD6B7]" : "text-[var(--rose)]"}>{check.ok ? "Pass" : "Fail"}</span>
          <span className="text-ink">{check.name.replaceAll("_", " ")}</span>
          <span className="text-[var(--muted)]">{check.detail}</span>
        </li>
      ))}
    </ul>
  );
}

export function AssetPreview({ asset }: { asset: GrowthAsset }) {
  const size = asset.width && asset.height ? `${asset.width}×${asset.height}` : "size unknown";
  return (
    <figure className="space-y-2">
      {asset.mime.startsWith("video/") ? (
        <video src={asset.preview_url} controls muted playsInline className="max-h-80 w-auto rounded-md border border-[var(--line)]" />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={asset.preview_url} alt={`${asset.role} ${asset.position + 1}`} className="max-h-80 w-auto rounded-md border border-[var(--line)]" />
      )}
      <figcaption className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
        <span>
          {asset.role} {asset.position + 1} · {size}
          {asset.duration_ms ? ` · ${(asset.duration_ms / 1000).toFixed(1)} s` : ""}
        </span>
        <StatusTag status={asset.quality_state} />
        <ProvenanceTag value={asset.provenance} />
        {asset.public_media_ready ? null : <span>Not yet at a public https address</span>}
      </figcaption>
    </figure>
  );
}

export function ModeNotice({ publishMode, insightsMode }: { publishMode: string; insightsMode: string }) {
  if (publishMode === "live" && insightsMode === "live") return null;
  return (
    <Notice
      kind="warn"
      title="Live Meta calls are off in this deployment"
      body={`Publishing is ${publishMode} and insight reads are ${insightsMode}. Plans, creative, and reviews work. Nothing is posted and no metric is read until an administrator enables the live modes and the workspace is authorized.`}
    />
  );
}
