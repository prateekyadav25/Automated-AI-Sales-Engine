"use client";

import { CommandPalette } from "@/components/command-palette";
import { CopilotDrawer } from "@/components/copilot-drawer";
import { DograhEmbed } from "@/components/dograh-embed";
import { Icon } from "@/components/icon";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { activeWorkspace, breadcrumbs, WORKSPACES } from "@/lib/navigation";
import { ROLE_PREVIEWS, RolePreviewProvider, useRolePreview } from "@/lib/role-preview";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

const WORKSPACE_ICON: Record<string, string> = {
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

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function ShellFrame({ children }: { children: React.ReactNode }) {
  const { user, loading, logout, can } = useAuth();
  const { role, setRole } = useRolePreview();
  const router = useRouter();
  const pathname = usePathname();
  const [palette, setPalette] = useState(false);
  const [copilot, setCopilot] = useState(false);
  const [seed, setSeed] = useState("");
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  const visible = useMemo(
    () =>
      WORKSPACES.map((workspace) => ({
        ...workspace,
        children: workspace.children.filter((item) => !item.permission || can(item.permission)),
      })).filter((workspace) => workspace.children.length > 0),
    [can],
  );

  if (loading || !user) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-[var(--dim)]">Restoring session</div>;
  }

  const current = activeWorkspace(pathname);
  const trail = breadcrumbs(pathname);
  const mark = initials(user.name) || "SE";

  return (
    <div className="app-shell">
      {navOpen ? <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)} /> : null}
      <aside className={cn("sidebar", navOpen && "open")} id="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark">
            <i />
            <i />
            <i />
          </span>
          Sales Engine
        </Link>
        <div className="tenant">
          <span className="avatar">AA</span>
          <div>
            <strong>AGRAYIAN AI LABS</strong>
            <div className="small muted">Revenue workspace</div>
          </div>
        </div>
        <div className="upper side-label">Revenue operation</div>
        <nav aria-label="Primary workspaces">
          {visible
            .filter((workspace) => workspace.id !== "settings")
            .map((workspace) => {
              const open = current?.id === workspace.id;
              return (
                <div key={workspace.id}>
                  <a className={cn("nav-item", open && "active")} href={workspace.children[0]?.href ?? workspace.href}>
                    <Icon name={WORKSPACE_ICON[workspace.id] ?? "document"} />
                    {workspace.label}
                  </a>
                  {open ? (
                    <div className="nav-sub">
                      {workspace.children.map((item) => (
                        <a key={item.href} className={pathname === item.href ? "active" : ""} href={item.href}>
                          {item.label}
                        </a>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
        </nav>
        <div className="side-bottom">
          <a className={cn("nav-item", current?.id === "settings" && "active")} href="/settings/company">
            <Icon name="settings" />
            Settings
          </a>
          {current?.id === "settings" ? (
            <div className="nav-sub">
              {visible.find((workspace) => workspace.id === "settings")?.children.map((item) => (
                <a key={item.href} className={pathname === item.href ? "active" : ""} href={item.href}>
                  {item.label}
                </a>
              ))}
            </div>
          ) : null}
          <a className="nav-item" href="/flow">
            <Icon name="workflow" />
            Revenue journey
          </a>
          <a className="nav-item" href="/screens">
            <Icon name="eye" />
            All page designs
          </a>
          <div className="operator">
            <span className="avatar">{mark}</span>
            <div>
              {user.name}
              <div className="small muted">{role}</div>
            </div>
          </div>
          <button className="sign-out" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <button className="btn iconbtn mobile-menu" aria-label="Open navigation" onClick={() => setNavOpen(true)}>
            <Icon name="menu" />
          </button>
          <div className="crumb">
            <span>{trail[0]?.label ?? "Command Centre"}</span>
            <Icon name="chevron" />
            <span>{trail[trail.length - 1]?.label ?? "Overview"}</span>
          </div>
          <div className="top-right">
            <button className="searchbutton" onClick={() => setPalette(true)}>
              <Icon name="search" />
              <span>Find a page or record</span>
              <kbd>⌘ K</kbd>
            </button>
            <select
              className="role-pick"
              aria-label="Workspace role"
              value={role}
              onChange={(event) => {
                const next = ROLE_PREVIEWS.find((item) => item === event.target.value);
                if (next) setRole(next);
              }}
            >
              {ROLE_PREVIEWS.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
            <a className="btn iconbtn" href="/automation/approvals" aria-label="Open decisions">
              <Icon name="bell" />
            </a>
            <button
              className="btn iconbtn"
              aria-label="Open contextual copilot"
              onClick={() => {
                setSeed("");
                setCopilot(true);
              }}
            >
              <Icon name="spark" />
            </button>
            <span className="avatar">{mark}</span>
          </div>
        </header>
        <main className="content" id="main">
          {children}
        </main>
      </div>
      <CommandPalette
        open={palette}
        onClose={() => setPalette(false)}
        onAsk={(query) => {
          setSeed(query);
          setCopilot(true);
        }}
      />
      <CopilotDrawer open={copilot} seed={seed} onClose={() => setCopilot(false)} />
      <DograhEmbed />
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <RolePreviewProvider>
      <ShellFrame>{children}</ShellFrame>
    </RolePreviewProvider>
  );
}
