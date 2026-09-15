import { createHmac } from "crypto";
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

function sign(body: string) {
  const secret = process.env.INTEGRATIONS_WEBHOOK_SECRET || process.env.SECRET_KEY || "change-me-to-a-long-random-string";
  return createHmac("sha256", secret).update(body).digest("hex");
}

test("usage webhook lights the 360 LIVE card and mapping confirm works", async ({ page, request }) => {
  const token = await apiLogin(request);
  const auth = { Authorization: `Bearer ${token}` };
  const stamp = Date.now();
  const domain = `signals${stamp}.example`;
  const account = await request.post(`${API}/api/v1/accounts`, {
    headers: auth,
    data: { name: `Signals E2E ${stamp}`, industry: "bfsi", domain },
  });
  expect(account.ok()).toBeTruthy();
  const accountId = (await account.json()).data.id as string;
  const opp = await request.post(`${API}/api/v1/opportunities`, {
    headers: auth,
    data: { account_id: accountId, name: `Signals E2E ${stamp} Deal`, stage: "commit", amount: "77000", probability: 90 },
  });
  const oppId = (await opp.json()).data.id as string;
  const won = await request.post(`${API}/api/v1/opportunities/${oppId}/close-won`, { headers: auth });
  const customerId = (await won.json()).data.id as string;
  const connectors = await request.get(`${API}/api/v1/integrations/connectors`, { headers: auth });
  expect(connectors.ok()).toBeTruthy();
  const usage = ((await connectors.json()).data as { provider: string; webhook_url: string }[]).find((row) => row.provider === "usage");
  expect(usage?.webhook_url).toBeTruthy();
  const body = JSON.stringify({
    external_id: `e2e-use-${stamp}`,
    event_type: "user.active",
    domain,
    user_id: "e2e-user",
  });
  const hook = await request.post(`${API}${usage?.webhook_url}`, {
    headers: { "X-Webhook-Signature": sign(body), "Content-Type": "application/json" },
    data: body,
  });
  expect(hook.ok()).toBeTruthy();

  await uiLogin(page);
  await page.goto(`/customers/${customerId}`);
  await expect(page.getByTestId("freshness-usage")).toContainText("LIVE");
  await expect(page.getByTestId("health-score")).toContainText("rules-v2");

  const fuzzyBody = JSON.stringify({
    external_id: `e2e-map-${stamp}`,
    event_type: "user.active",
    account_name: `Signals E2E ${stamp}`,
    account_external_id: `ext-${stamp}`,
    user_id: "mapper",
  });
  await request.post(`${API}${usage?.webhook_url}`, {
    headers: { "X-Webhook-Signature": sign(fuzzyBody), "Content-Type": "application/json" },
    data: fuzzyBody,
  });
  await page.goto("/admin/integrations");
  await expect(page.getByTestId("signal-connectors")).toBeVisible();
  await expect(page.getByTestId("entity-mappings")).toBeVisible();
  await page.getByRole("button", { name: "Confirm" }).first().click();
  await expect(page.getByText("confirmed").first()).toBeVisible();
});

test("stale usage, overdue invoice, and high utilization stay honest", async ({ page, request }) => {
  const token = await apiLogin(request);
  const auth = { Authorization: `Bearer ${token}` };
  const stamp = Date.now();
  const domain = `stale${stamp}.example`;
  await request.patch(`${API}/api/v1/autonomy/settings`, {
    headers: auth,
    data: { enabled: true, customer_health_enabled: true, customer_success_enabled: true, upsell_enabled: true, expansion_auto_opportunity_enabled: false },
  });
  const account = await request.post(`${API}/api/v1/accounts`, {
    headers: auth,
    data: { name: `Stale E2E ${stamp}`, industry: "bfsi", domain },
  });
  const accountId = (await account.json()).data.id as string;
  const opp = await request.post(`${API}/api/v1/opportunities`, {
    headers: auth,
    data: { account_id: accountId, name: `Stale E2E ${stamp} Deal`, stage: "commit", amount: "88000", probability: 90 },
  });
  const oppId = (await opp.json()).data.id as string;
  const products = await request.get(`${API}/api/v1/lifecycle/products`, { headers: auth });
  const productId = ((await products.json()).data as { id: string }[])[0]?.id;
  if (productId) {
    await request.post(`${API}/api/v1/lifecycle/quotes`, {
      headers: auth,
      data: { opportunity_id: oppId, discount_pct: 0, tax_pct: 0, lines: [{ product_id: productId, quantity: 10 }] },
    });
  }
  const won = await request.post(`${API}/api/v1/opportunities/${oppId}/close-won`, { headers: auth });
  const customerId = (await won.json()).data.id as string;
  const connectors = await request.get(`${API}/api/v1/integrations/connectors`, { headers: auth });
  const rows = (await connectors.json()).data as { provider: string; webhook_url: string }[];
  const usage = rows.find((row) => row.provider === "usage");
  const finance = rows.find((row) => row.provider === "finance");
  expect(usage?.webhook_url).toBeTruthy();
  const staleAt = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString();
  const staleBody = JSON.stringify({
    external_id: `e2e-stale-${stamp}`,
    event_type: "user.active",
    domain,
    user_id: "stale-user",
    observed_at: staleAt,
  });
  const staleHook = await request.post(`${API}${usage?.webhook_url}`, {
    headers: { "X-Webhook-Signature": sign(staleBody), "Content-Type": "application/json" },
    data: staleBody,
  });
  expect(staleHook.ok()).toBeTruthy();
  const detail = await request.get(`${API}/api/v1/post-sale/customers/${customerId}`, { headers: auth });
  const card = (await detail.json()).data as {
    usage_freshness: string;
    unavailable_components: string;
    health_components?: Record<string, { status?: string }>;
  };
  expect(card.usage_freshness).toBe("STALE");
  expect(card.unavailable_components).toContain("usage");

  const invoice = JSON.stringify({
    external_id: `e2e-inv-${stamp}`,
    event_type: "invoice.overdue",
    invoice_id: `e2e-inv-${stamp}`,
    domain,
    amount: "1400",
    currency: "INR",
    days_past_due: 21,
  });
  const financeHook = await request.post(`${API}${finance?.webhook_url}`, {
    headers: { "X-Webhook-Signature": sign(invoice), "Content-Type": "application/json" },
    data: invoice,
  });
  expect(financeHook.ok()).toBeTruthy();
  const afterFinance = await request.get(`${API}/api/v1/post-sale/customers/${customerId}`, { headers: auth });
  const risks = ((await afterFinance.json()).data.risks as { risk_type: string }[]) ?? [];
  expect(risks.some((row) => row.risk_type === "COMMERCIAL_RISK")).toBeTruthy();

  for (let index = 0; index < 9; index += 1) {
    const seat = JSON.stringify({
      external_id: `e2e-seat-${stamp}-${index}`,
      event_type: "seat.active",
      domain,
      user_id: `seat-${index}`,
    });
    await request.post(`${API}${usage?.webhook_url}`, {
      headers: { "X-Webhook-Signature": sign(seat), "Content-Type": "application/json" },
      data: seat,
    });
  }
  const recs = await request.get(`${API}/api/v1/post-sale/expansion`, { headers: auth });
  const mine = ((await recs.json()).data as { customer_id: string; kind: string; opportunity_id: string | null; title: string }[]).filter(
    (row) => row.customer_id === customerId && row.kind === "upsell",
  );
  expect(mine.length).toBeGreaterThan(0);
  expect(mine.every((row) => row.opportunity_id == null)).toBeTruthy();
  const opps = await request.get(`${API}/api/v1/opportunities`, { headers: auth });
  expect(((await opps.json()).data as { name: string }[]).some((row) => row.name === "Seat saturation")).toBeFalsy();

  await uiLogin(page);
  await page.goto(`/customers/${customerId}`);
  await expect(page.getByTestId("freshness-usage")).toContainText("LIVE");
  await expect(page.getByTestId("freshness-finance")).toContainText("LIVE");
});
