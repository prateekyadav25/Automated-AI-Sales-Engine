import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiLogin(request: APIRequestContext) {
  const response = await request.post(`${API}/api/v1/auth/login`, {
    data: { email: "admin@agrayian.demo", password: "Agrarian!Demo1" },
  });
  expect(response.ok()).toBeTruthy();
  const json = await response.json();
  return json.data.access_token as string;
}

async function uiLogin(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@agrayian.demo");
  await page.getByLabel("Password").fill("Agrarian!Demo1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/");
}

async function createLead(request: APIRequestContext, token: string, email: string) {
  await request.patch(`${API}/api/v1/autonomy/settings`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { enabled: true },
  });
  const accounts = await request.get(`${API}/api/v1/accounts`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const accountId = ((await accounts.json()).data as { id: string; name: string }[]).find((row) => row.name === "Meridian Bank")?.id;
  const created = await request.post(`${API}/api/v1/leads`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      first_name: "Play",
      last_name: "Wright",
      email,
      company_name: "Meridian Bank",
      title: "CIO",
      account_id: accountId,
      consent_email: true,
      intent_score: 80,
      engagement_score: 70,
      has_buying_trigger: true,
    },
  });
  expect(created.ok()).toBeTruthy();
  return (await created.json()).data;
}

test("consented lead approve shows sent activity", async ({ page, request }) => {
  const token = await apiLogin(request);
  const lead = await createLead(request, token, `play.send.${Date.now()}@meridianbank.example`);
  const approvals = await request.get(`${API}/api/v1/ai/approvals`, { headers: { Authorization: `Bearer ${token}` } });
  const approval = ((await approvals.json()).data as { id: string; entity_id: string; action_type: string }[]).find(
    (row) => row.entity_id === lead.id && row.action_type.endsWith(".send"),
  );
  expect(approval).toBeTruthy();
  await request.post(`${API}/api/v1/ai/approvals/${approval!.id}/decide`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { decision: "approve", note: "e2e" },
  });
  await uiLogin(page);
  await page.goto("/conversations");
  await expect(page.getByRole("heading", { name: "Conversations" })).toBeVisible();
  await expect(page.getByText("Follow-up").first()).toBeVisible();
});

test("injected reply is classified", async ({ page, request }) => {
  const token = await apiLogin(request);
  const lead = await createLead(request, token, `play.reply.${Date.now()}@meridianbank.example`);
  await request.post(`${API}/api/v1/integrations/inbox/simulate`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      from_addr: lead.email,
      subject: "Question",
      body_text: "What is the pricing?",
      provider_message_id: `q-${Date.now()}`,
    },
  });
  await uiLogin(page);
  await page.goto("/automation/approvals");
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  await expect(page.getByText("Reply to").first()).toBeVisible();
});

test("meeting request can be booked", async ({ page, request }) => {
  const token = await apiLogin(request);
  const lead = await createLead(request, token, `play.meet.${Date.now()}@meridianbank.example`);
  await request.post(`${API}/api/v1/integrations/inbox/simulate`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      from_addr: lead.email,
      subject: "Meet",
      body_text: "Let's meet. I am available to meet.",
      provider_message_id: `m-${Date.now()}`,
    },
  });
  const start = new Date(Date.now() + 86400000).toISOString();
  const end = new Date(Date.now() + 86400000 + 1800000).toISOString();
  const queued = await request.post(`${API}/api/v1/integrations/calendar/book`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { lead_id: lead.id, start_at: start, end_at: end, timezone: "UTC", title: "E2E meeting" },
  });
  const approvalId = (await queued.json()).data.approval_id;
  await request.post(`${API}/api/v1/ai/approvals/${approvalId}/decide`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { decision: "approve", note: "book" },
  });
  await uiLogin(page);
  await page.goto("/meetings");
  await expect(page.getByRole("heading", { name: "Meetings" })).toBeVisible();
  await expect(page.getByText("E2E meeting").first()).toBeVisible();
});

test("unsubscribe suppresses the lead", async ({ request }) => {
  const token = await apiLogin(request);
  const lead = await createLead(request, token, `play.unsub.${Date.now()}@meridianbank.example`);
  await request.post(`${API}/api/v1/integrations/inbox/simulate`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      from_addr: lead.email,
      subject: "Stop",
      body_text: "Unsubscribe me from this list.",
      provider_message_id: `u-${Date.now()}`,
    },
  });
  const refreshed = await request.get(`${API}/api/v1/leads/${lead.id}`, { headers: { Authorization: `Bearer ${token}` } });
  expect((await refreshed.json()).data.opt_out).toBeTruthy();
});

test("double approve sends once", async ({ request }) => {
  const token = await apiLogin(request);
  const lead = await createLead(request, token, `play.once.${Date.now()}@meridianbank.example`);
  const approvals = await request.get(`${API}/api/v1/ai/approvals`, { headers: { Authorization: `Bearer ${token}` } });
  const approval = ((await approvals.json()).data as { id: string; entity_id: string; action_type: string }[]).find(
    (row) => row.entity_id === lead.id && row.action_type.endsWith(".send"),
  );
  await request.post(`${API}/api/v1/ai/approvals/${approval!.id}/decide`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { decision: "approve", note: "one" },
  });
  await request.post(`${API}/api/v1/ai/approvals/${approval!.id}/decide`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { decision: "approve", note: "two" },
  });
  const conversations = await request.get(`${API}/api/v1/lifecycle/conversations`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const outbound = ((await conversations.json()).data as { lead_id?: string; messages?: { direction: string }[] }[])
    .filter((row) => row.lead_id === lead.id)
    .flatMap((row) => row.messages ?? [])
    .filter((row) => row.direction === "outbound");
  expect(outbound).toHaveLength(1);
});
