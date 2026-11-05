export type PageEntry = {
  href: string;
  label: string;
  workspace: string;
  permission?: string;
};

export type WorkspaceNav = {
  id: string;
  label: string;
  href: string;
  permission?: string;
  children: { href: string; label: string; permission?: string }[];
};

export const PAGES: PageEntry[] = [
  { href: "/", label: "Overview", workspace: "Command Centre", permission: "command_center.read" },
  { href: "/intelligence", label: "AI research workspace", workspace: "Command Centre", permission: "ai.copilot" },
  { href: "/flow", label: "Revenue journey", workspace: "Command Centre", permission: "command_center.read" },
  { href: "/strategy", label: "Revenue strategy", workspace: "Strategy & Intelligence", permission: "icps.read" },
  { href: "/icps", label: "Ideal customer profiles", workspace: "Strategy & Intelligence", permission: "icps.read" },
  { href: "/market", label: "Market overview", workspace: "Strategy & Intelligence", permission: "markets.read" },
  { href: "/market/signals", label: "Signal inbox", workspace: "Strategy & Intelligence", permission: "markets.read" },
  { href: "/market/triggers", label: "Signal triggers", workspace: "Strategy & Intelligence", permission: "markets.read" },
  { href: "/site-signals", label: "Website signals", workspace: "Strategy & Intelligence", permission: "signals.read" },
  { href: "/campaigns", label: "Campaigns", workspace: "Marketing", permission: "campaigns.read" },
  { href: "/channel-search", label: "Channel search", workspace: "Marketing", permission: "campaigns.read" },
  { href: "/content", label: "Content studio", workspace: "Marketing", permission: "campaigns.read" },
  { href: "/social", label: "Social", workspace: "Marketing", permission: "campaigns.read" },
  { href: "/calendar", label: "Calendar", workspace: "Marketing", permission: "meetings.read" },
  { href: "/acquisition", label: "Inbound", workspace: "Marketing", permission: "acquisition.read" },
  { href: "/growth", label: "Social Growth Command Center", workspace: "Social Growth", permission: "social_growth.read" },
  { href: "/growth/brand", label: "Brand intelligence", workspace: "Social Growth", permission: "social_growth.read" },
  { href: "/growth/accounts", label: "Connected accounts", workspace: "Social Growth", permission: "social_growth.read" },
  { href: "/growth/calendar", label: "Strategy & calendar", workspace: "Social Growth", permission: "social_growth.read" },
  { href: "/growth/studio", label: "Creative studio", workspace: "Social Growth", permission: "social_growth.read" },
  { href: "/growth/performance", label: "Performance & leads", workspace: "Social Growth", permission: "social_growth.read" },
  { href: "/leads", label: "Leads", workspace: "Sales", permission: "leads.read" },
  { href: "/accounts", label: "Accounts", workspace: "Sales", permission: "accounts.read" },
  { href: "/contacts", label: "Contacts", workspace: "Sales", permission: "contacts.read" },
  { href: "/imports", label: "Import", workspace: "Sales", permission: "leads.write" },
  { href: "/sequences", label: "Sequences", workspace: "Sales", permission: "sequences.read" },
  { href: "/sequences/builder", label: "Sequence builder", workspace: "Sales", permission: "sequences.write" },
  { href: "/conversations", label: "Conversations", workspace: "Sales", permission: "conversations.read" },
  { href: "/meetings", label: "Meetings", workspace: "Sales", permission: "meetings.read" },
  { href: "/automation/voice-scripts", label: "Voice", workspace: "Sales", permission: "conversations.read" },
  { href: "/automation/test-call", label: "Test call", workspace: "Sales", permission: "conversations.read" },
  { href: "/pipeline", label: "Pipeline", workspace: "Sales", permission: "opportunities.read" },
  { href: "/deals", label: "Deal risk", workspace: "Sales", permission: "deals.read" },
  { href: "/tasks", label: "Work queue", workspace: "Sales", permission: "tasks.read" },
  { href: "/commercial", label: "Quotes", workspace: "Commercial", permission: "commercial.read" },
  { href: "/commercial/proposal", label: "Proposal", workspace: "Commercial", permission: "commercial.read" },
  { href: "/commercial/contracts", label: "Contracts", workspace: "Commercial", permission: "commercial.read" },
  { href: "/customers", label: "Portfolio", workspace: "Customers", permission: "accounts.read" },
  { href: "/onboarding", label: "Onboarding", workspace: "Customers", permission: "success.read" },
  { href: "/success", label: "Success", workspace: "Customers", permission: "success.read" },
  { href: "/renewals", label: "Renewals", workspace: "Customers", permission: "success.read" },
  { href: "/expansion", label: "Expansion", workspace: "Customers", permission: "success.read" },
  { href: "/advocacy", label: "Advocacy", workspace: "Customers", permission: "advocacy.read" },
  { href: "/automation/runs", label: "Execution centre", workspace: "Autopilot", permission: "autonomy.read" },
  { href: "/automation/approvals", label: "Decision inbox", workspace: "Autopilot", permission: "ai.approvals.read" },
  { href: "/playbooks", label: "Playbooks", workspace: "Autopilot", permission: "revops.read" },
  { href: "/playbooks/builder", label: "Playbook builder", workspace: "Autopilot", permission: "revops.read" },
  { href: "/policies", label: "Policies", workspace: "Autopilot", permission: "autonomy.read" },
  { href: "/forecast", label: "Forecast", workspace: "Insights", permission: "forecast.read" },
  { href: "/insights/attribution", label: "Attribution", workspace: "Insights", permission: "campaigns.read" },
  { href: "/insights/retention", label: "Cohorts", workspace: "Insights", permission: "forecast.read" },
  { href: "/insights/automation", label: "Automation performance", workspace: "Insights", permission: "pilot.view" },
  { href: "/settings/company", label: "Company", workspace: "Settings", permission: "campaigns.read" },
  { href: "/setup", label: "Launch", workspace: "Settings", permission: "autonomy.read" },
  { href: "/launch", label: "Launch checklist", workspace: "Settings", permission: "autonomy.read" },
  { href: "/knowledge", label: "Knowledge", workspace: "Settings", permission: "knowledge.read" },
  { href: "/models", label: "Models", workspace: "Settings", permission: "revops.read" },
  { href: "/admin/integrations", label: "Connections", workspace: "Settings", permission: "integrations.read" },
  { href: "/admin/users", label: "People", workspace: "Settings", permission: "users.read" },
  { href: "/admin/teams", label: "Teams", workspace: "Settings", permission: "teams.read" },
  { href: "/admin/flags", label: "Flags", workspace: "Settings", permission: "flags.read" },
  { href: "/admin/audit", label: "Audit", workspace: "Settings", permission: "audit.read" },
  { href: "/admin/pilot", label: "Readiness", workspace: "Settings", permission: "pilot.view" },
  { href: "/security", label: "Security", workspace: "Settings", permission: "pilot.view" },
  { href: "/design-system", label: "Design system", workspace: "Settings" },
  { href: "/screens", label: "All page designs", workspace: "Settings" },
];

export const WORKSPACES: WorkspaceNav[] = [
  {
    id: "command",
    label: "Command Centre",
    href: "/",
    permission: "command_center.read",
    children: [
      { href: "/", label: "Overview", permission: "command_center.read" },
      { href: "/intelligence", label: "AI research workspace", permission: "ai.copilot" },
    ],
  },
  {
    id: "strategy",
    label: "Strategy & Intelligence",
    href: "/strategy",
    permission: "icps.read",
    children: [
      { href: "/strategy", label: "Revenue strategy", permission: "icps.read" },
      { href: "/icps", label: "Ideal customer profiles", permission: "icps.read" },
      { href: "/market", label: "Market overview", permission: "markets.read" },
      { href: "/market/signals", label: "Signal inbox", permission: "markets.read" },
      { href: "/market/triggers", label: "Signal triggers", permission: "markets.read" },
      { href: "/site-signals", label: "Website signals", permission: "signals.read" },
    ],
  },
  {
    id: "marketing",
    label: "Marketing",
    href: "/campaigns",
    permission: "campaigns.read",
    children: [
      { href: "/campaigns", label: "Campaigns", permission: "campaigns.read" },
      { href: "/channel-search", label: "Channel search", permission: "campaigns.read" },
      { href: "/content", label: "Content studio", permission: "campaigns.read" },
      { href: "/social", label: "Social publishing", permission: "campaigns.read" },
      { href: "/calendar", label: "Marketing calendar", permission: "meetings.read" },
      { href: "/acquisition", label: "Inbound acquisition", permission: "acquisition.read" },
    ],
  },
  {
    id: "growth",
    label: "Social Growth",
    href: "/growth",
    permission: "social_growth.read",
    children: [
      { href: "/growth", label: "Command center", permission: "social_growth.read" },
      { href: "/growth/brand", label: "Brand intelligence", permission: "social_growth.read" },
      { href: "/growth/accounts", label: "Connected accounts", permission: "social_growth.read" },
      { href: "/growth/calendar", label: "Strategy & calendar", permission: "social_growth.read" },
      { href: "/growth/studio", label: "Creative studio", permission: "social_growth.read" },
      { href: "/growth/performance", label: "Performance & leads", permission: "social_growth.read" },
    ],
  },
  {
    id: "sales",
    label: "Sales",
    href: "/leads",
    permission: "leads.read",
    children: [
      { href: "/leads", label: "Leads", permission: "leads.read" },
      { href: "/accounts", label: "Accounts", permission: "accounts.read" },
      { href: "/contacts", label: "Contacts", permission: "contacts.read" },
      { href: "/imports", label: "Import centre", permission: "leads.write" },
      { href: "/sequences", label: "Outreach sequences", permission: "sequences.read" },
      { href: "/conversations", label: "Conversations", permission: "conversations.read" },
      { href: "/meetings", label: "Meetings", permission: "meetings.read" },
      { href: "/automation/voice-scripts", label: "Voice workspace", permission: "conversations.read" },
      { href: "/automation/test-call", label: "Test call", permission: "conversations.read" },
      { href: "/pipeline", label: "Opportunity pipeline", permission: "opportunities.read" },
      { href: "/deals", label: "Deal risk", permission: "deals.read" },
      { href: "/tasks", label: "Work queue", permission: "tasks.read" },
    ],
  },
  {
    id: "commercial",
    label: "Commercial",
    href: "/commercial",
    permission: "commercial.read",
    children: [
      { href: "/commercial", label: "Quotes & catalog", permission: "commercial.read" },
      { href: "/commercial/proposal", label: "Proposal workspace", permission: "commercial.read" },
      { href: "/commercial/contracts", label: "Contracts", permission: "commercial.read" },
    ],
  },
  {
    id: "customers",
    label: "Customers",
    href: "/customers",
    permission: "accounts.read",
    children: [
      { href: "/customers", label: "Customer portfolio", permission: "accounts.read" },
      { href: "/onboarding", label: "Onboarding", permission: "success.read" },
      { href: "/success", label: "Customer success", permission: "success.read" },
      { href: "/renewals", label: "Renewals", permission: "success.read" },
      { href: "/expansion", label: "Expansion", permission: "success.read" },
      { href: "/advocacy", label: "Advocacy", permission: "advocacy.read" },
    ],
  },
  {
    id: "autopilot",
    label: "Autopilot",
    href: "/automation/runs",
    permission: "autonomy.read",
    children: [
      { href: "/automation/runs", label: "Execution centre", permission: "autonomy.read" },
      { href: "/automation/approvals", label: "Decision inbox", permission: "ai.approvals.read" },
      { href: "/playbooks", label: "Journey playbooks", permission: "revops.read" },
      { href: "/policies", label: "Autonomy & policies", permission: "autonomy.read" },
    ],
  },
  {
    id: "insights",
    label: "Insights",
    href: "/forecast",
    permission: "forecast.read",
    children: [
      { href: "/forecast", label: "Revenue forecast", permission: "forecast.read" },
      { href: "/insights/attribution", label: "Campaign attribution", permission: "campaigns.read" },
      { href: "/insights/retention", label: "Customer cohorts", permission: "forecast.read" },
      { href: "/insights/automation", label: "Automation performance", permission: "pilot.view" },
    ],
  },
  {
    id: "settings",
    label: "Settings",
    href: "/settings/company",
    permission: "campaigns.read",
    children: [
      { href: "/settings/company", label: "Company & workspace", permission: "campaigns.read" },
      { href: "/setup", label: "Revenue launch", permission: "autonomy.read" },
      { href: "/knowledge", label: "Knowledge library", permission: "knowledge.read" },
      { href: "/models", label: "AI & model governance", permission: "revops.read" },
      { href: "/admin/integrations", label: "Connections", permission: "integrations.read" },
      { href: "/admin/users", label: "People & access", permission: "users.read" },
      { href: "/admin/teams", label: "Teams & ownership", permission: "teams.read" },
      { href: "/admin/flags", label: "Feature controls", permission: "flags.read" },
      { href: "/admin/audit", label: "Audit trail", permission: "audit.read" },
      { href: "/admin/pilot", label: "Operational readiness", permission: "pilot.view" },
      { href: "/security", label: "Security & data", permission: "pilot.view" },
      { href: "/design-system", label: "Design system" },
    ],
  },
];

const WORKSPACE_ROOTS: Record<string, string[]> = {
  command: ["/", "/intelligence", "/flow"],
  strategy: ["/strategy", "/icps", "/market", "/site-signals"],
  marketing: ["/campaigns", "/channel-search", "/content", "/social", "/calendar", "/acquisition"],
  growth: ["/growth"],
  sales: ["/leads", "/accounts", "/contacts", "/imports", "/sequences", "/conversations", "/meetings", "/automation/voice-scripts", "/automation/test-call", "/pipeline", "/deals", "/tasks", "/opportunities"],
  commercial: ["/commercial"],
  customers: ["/customers", "/onboarding", "/success", "/renewals", "/expansion", "/advocacy"],
  autopilot: ["/automation", "/playbooks", "/policies", "/launch"],
  insights: ["/forecast", "/insights"],
  settings: ["/settings", "/setup", "/knowledge", "/models", "/admin", "/security", "/design-system", "/screens"],
};

export function activeWorkspace(pathname: string): WorkspaceNav | undefined {
  if (pathname === "/") return WORKSPACES.find((item) => item.id === "command");
  return WORKSPACES.find((workspace) =>
    (WORKSPACE_ROOTS[workspace.id] ?? []).some((root) => root !== "/" && (pathname === root || pathname.startsWith(`${root}/`))),
  );
}

export function breadcrumbs(pathname: string): { href: string; label: string }[] {
  const workspace = activeWorkspace(pathname);
  const exact = PAGES.find((page) => page.href === pathname);
  if (exact && workspace) {
    if (exact.href === workspace.href) return [{ href: workspace.href, label: workspace.label }, { href: exact.href, label: exact.label }];
    return [
      { href: workspace.href, label: workspace.label },
      { href: exact.href, label: exact.label },
    ];
  }
  const parent = PAGES.filter((page) => page.href !== "/" && pathname.startsWith(`${page.href}/`)).sort((a, b) => b.href.length - a.href.length)[0];
  const head = workspace ? [{ href: workspace.href, label: workspace.label }] : [{ href: "/", label: "Command Centre" }];
  if (parent) return [...head.filter((item) => item.href !== parent.href), { href: parent.href, label: parent.label }, { href: pathname, label: "Record" }];
  return head;
}
