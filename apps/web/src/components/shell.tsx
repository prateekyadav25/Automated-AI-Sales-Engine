"use client";

import { CommandPalette } from "@/components/command-palette";
import { CopilotDrawer } from "@/components/copilot-drawer";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  BookOpen,
  Briefcase,
  Building2,
  Calendar,
  CheckSquare,
  ChevronDown,
  ChevronLeft,
  ChevronsUpDown,
  CircleDollarSign,
  Flag,
  Handshake,
  HeartPulse,
  LayoutDashboard,
  Megaphone,
  MessageSquare,
  PanelLeft,
  RefreshCw,
  Repeat,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Bot,
  Target,
  TrendingUp,
  Upload,
  Users,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

const GROUPS = [
  {
    label: "Start here",
    defaultOpen: true,
    items: [
      { href: "/", label: "Home", permission: "command_center.read", icon: LayoutDashboard },
      { href: "/automation/runs", label: "Autopilot", permission: "autonomy.read", icon: Bot },
      { href: "/automation/approvals", label: "Approvals", permission: "ai.approvals.read", icon: ShieldCheck },
      { href: "/leads", label: "Leads", permission: "leads.read", icon: Target },
      { href: "/icps", label: "Who we sell to", permission: "icps.read", icon: Flag },
    ],
  },
  {
    label: "Records",
    defaultOpen: false,
    items: [
      { href: "/accounts", label: "Accounts", permission: "accounts.read", icon: Building2 },
      { href: "/contacts", label: "Contacts", permission: "contacts.read", icon: Users },
      { href: "/imports", label: "Import CSV", permission: "leads.write", icon: Upload },
      { href: "/tasks", label: "Tasks", permission: "tasks.read", icon: CheckSquare },
    ],
  },
  {
    label: "Sell",
    defaultOpen: false,
    items: [
      { href: "/pipeline", label: "Pipeline", permission: "opportunities.read", icon: Briefcase },
      { href: "/campaigns", label: "Campaigns", permission: "campaigns.read", icon: Megaphone },
      { href: "/sequences", label: "Sequences", permission: "sequences.read", icon: Repeat },
      { href: "/acquisition", label: "Inbound", permission: "acquisition.read", icon: Megaphone },
    ],
  },
  {
    label: "Meet",
    defaultOpen: false,
    items: [
      { href: "/conversations", label: "Conversations", permission: "conversations.read", icon: MessageSquare },
      { href: "/meetings", label: "Meetings", permission: "meetings.read", icon: Calendar },
    ],
  },
  {
    label: "After the sale",
    defaultOpen: false,
    items: [
      { href: "/deals", label: "Deal risk", permission: "deals.read", icon: Target },
      { href: "/commercial", label: "Quotes", permission: "commercial.read", icon: CircleDollarSign },
      { href: "/forecast", label: "Forecast", permission: "forecast.read", icon: TrendingUp },
      { href: "/customers", label: "Customers", permission: "accounts.read", icon: Handshake },
      { href: "/success", label: "Success", permission: "success.read", icon: HeartPulse },
      { href: "/renewals", label: "Renewals", permission: "success.read", icon: RefreshCw },
      { href: "/expansion", label: "Expansion", permission: "success.read", icon: ChevronsUpDown },
      { href: "/advocacy", label: "Advocacy", permission: "advocacy.read", icon: Handshake },
    ],
  },
  {
    label: "More",
    defaultOpen: false,
    items: [
      { href: "/intelligence", label: "Copilot", permission: "ai.copilot", icon: Sparkles },
      { href: "/knowledge", label: "Knowledge", permission: "knowledge.read", icon: BookOpen },
      { href: "/market", label: "Market", permission: "markets.read", icon: TrendingUp },
      { href: "/playbooks", label: "Playbooks", permission: "revops.read", icon: Workflow },
      { href: "/models", label: "Models", permission: "revops.read", icon: Settings },
      { href: "/admin/users", label: "People", permission: "users.read", icon: Users },
      { href: "/admin/teams", label: "Teams", permission: "teams.read", icon: Users },
      { href: "/admin/flags", label: "Flags", permission: "flags.read", icon: Flag },
      { href: "/admin/audit", label: "Audit", permission: "audit.read", icon: ShieldCheck },
    ],
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout, can } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [palette, setPalette] = useState(false);
  const [copilot, setCopilot] = useState(false);
  const [seed, setSeed] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(GROUPS.map((group) => [group.label, group.defaultOpen])),
  );

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    const match = GROUPS.find((group) =>
      group.items.some((item) => (item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`))),
    );
    if (!match) return;
    setOpenGroups((current) => ({ ...current, [match.label]: true }));
  }, [pathname]);

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

  const visibleGroups = useMemo(
    () =>
      GROUPS.map((group) => ({
        ...group,
        items: group.items.filter((item) => can(item.permission)),
      })).filter((group) => group.items.length),
    [can],
  );

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-[var(--muted)]">Restoring session</div>;
  }
  if (!user) return null;

  return (
    <div className="relative flex min-h-screen bg-transparent">
      <aside
        className={cn(
          "glass-strong sticky top-0 z-20 flex h-screen flex-col border-r transition-[width]",
          collapsed ? "w-[72px]" : "w-[248px]",
        )}
      >
        <div className={cn("flex items-center gap-2 px-4 py-5", collapsed && "justify-center px-2")}>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/70 bg-navy/90 text-xs font-bold text-white shadow-glass">
            A
          </div>
          {collapsed ? null : (
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-azure-600">AGRAYIAN</p>
              <p className="truncate text-sm font-semibold text-navy">Revenue OS</p>
            </div>
          )}
        </div>
        <nav className="flex-1 space-y-1 overflow-auto px-2 pb-4">
          {visibleGroups.map((group) => {
            const open = collapsed || openGroups[group.label];
            return (
              <div key={group.label}>
                {collapsed ? null : (
                  <button
                    type="button"
                    onClick={() => setOpenGroups((current) => ({ ...current, [group.label]: !current[group.label] }))}
                    className="mb-1 flex w-full items-center justify-between px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]"
                  >
                    {group.label}
                    <ChevronDown className={cn("h-3.5 w-3.5 transition", open ? "rotate-0" : "-rotate-90")} />
                  </button>
                )}
                {open
                  ? group.items.map((item) => {
                      const active =
                        item.href === "/"
                          ? pathname === "/"
                          : pathname === item.href || pathname.startsWith(`${item.href}/`);
                      const Icon = item.icon;
                      return (
                        <Link
                          key={item.href}
                          href={item.href}
                          title={item.label}
                          className={cn(
                            "mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition",
                            collapsed && "justify-center px-2",
                            active
                              ? "bg-azure-50 font-semibold text-azure-700"
                              : "text-slate-600 hover:bg-white/60 hover:text-ink",
                          )}
                        >
                          <Icon className="h-4 w-4 shrink-0" />
                          {collapsed ? null : item.label}
                        </Link>
                      );
                    })
                  : null}
              </div>
            );
          })}
        </nav>
        <div className="border-t border-[var(--line)] p-2">
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="flex w-full items-center justify-center gap-2 rounded-lg px-2 py-2 text-xs text-[var(--muted)] hover:bg-white/60"
          >
            {collapsed ? <PanelLeft className="h-4 w-4" /> : <><ChevronLeft className="h-4 w-4" /> Collapse</>}
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="glass-strong sticky top-0 z-30 flex items-center justify-between border-b px-6 py-3">
          <button
            onClick={() => setPalette(true)}
            className="flex min-w-[280px] items-center gap-2 rounded-lg border border-[var(--line)] bg-white/70 px-3 py-2 text-left text-sm text-[var(--muted)] hover:border-azure-600/40"
          >
            <Search className="h-4 w-4" />
            Search accounts, leads, deals…
            <span className="ml-auto text-[11px] text-slate-400">⌘K</span>
          </button>
          <div className="flex items-center gap-3 text-sm">
            <button
              className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-600"
              onClick={() => setCopilot(true)}
            >
              Copilot
            </button>
            <div className="text-right">
              <p className="font-medium text-ink">{user.name}</p>
              <p className="text-[11px] text-[var(--muted)]">{user.roles[0]}</p>
            </div>
            <button
              className="text-[var(--muted)] hover:text-ink"
              onClick={() => void logout().then(() => router.push("/login"))}
            >
              Sign out
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-7">{children}</main>
      </div>
      <CommandPalette
        open={palette}
        onClose={() => setPalette(false)}
        onAsk={(q) => {
          setSeed(q);
          setCopilot(true);
        }}
      />
      <CopilotDrawer open={copilot} seed={seed} onClose={() => setCopilot(false)} />
    </div>
  );
}
