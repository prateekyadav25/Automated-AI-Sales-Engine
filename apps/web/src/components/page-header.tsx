"use client";

import { Icon } from "@/components/icon";
import { activeWorkspace } from "@/lib/navigation";
import { screenForPath } from "@/lib/screen-copy";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const ICONS: Record<string, string> = {
  command: "dashboard",
  strategy: "compass",
  marketing: "megaphone",
  growth: "spark",
  sales: "briefcase",
  commercial: "document",
  customers: "heart",
  autopilot: "workflow",
  insights: "chart",
  settings: "settings",
};

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  nextHref,
  nextLabel,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
  nextHref?: string;
  nextLabel?: string;
}) {
  const pathname = usePathname();
  const workspace = activeWorkspace(pathname);
  const screen = screenForPath(pathname);
  const listScreen = screen && !screen.detail ? screen : null;
  const context = workspace?.label || eyebrow || "Sales Engine";
  const heading = listScreen?.title || title;
  const description = listScreen?.description || subtitle;
  const concrete = (href?: string | null) => (href && !href.includes("[") ? href : undefined);
  const handoffHref = concrete(nextHref) || (pathname === "/" ? undefined : concrete(listScreen?.nextHref));
  const handoffLabel = nextLabel || listScreen?.nextLabel;
  return (
    <div className="page-head">
      <div>
        <div className="context">
          <Icon name={ICONS[workspace?.id ?? ""] ?? "document"} />
          {context}
        </div>
        <h1>{heading}</h1>
        {description ? <p className="subtitle">{description}</p> : null}
      </div>
      <div className="ds-flex">
        {handoffHref && handoffLabel ? (
          <Link className="btn" href={handoffHref}>
            Next: {handoffLabel}
          </Link>
        ) : null}
        {actions}
      </div>
    </div>
  );
}
