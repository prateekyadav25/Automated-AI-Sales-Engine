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

test("pilot readiness activate and config export", async ({ page, request }) => {
  const token = await apiLogin(request);
  const readiness = await request.get(`${API}/api/v1/pilot/readiness`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(readiness.ok()).toBeTruthy();
  await uiLogin(page);
  await page.goto("/admin/pilot");
  await expect(page.getByRole("heading", { name: "Pilot readiness" })).toBeVisible();
  await expect(page.getByTestId("pilot-checklist")).toBeVisible();
  await expect(page.getByTestId("config-export")).toBeVisible();
  await page.getByTestId("activate-pilot").click();
  await expect(page.getByTestId("pilot-mode")).toContainText("PILOT", { timeout: 15000 });
});

test("models readiness shows pending history and not ready", async ({ page }) => {
  await uiLogin(page);
  await page.goto("/models");
  await expect(page.getByTestId("readiness-heading")).toBeVisible();
  await expect(page.getByText("Pending").first()).toBeVisible();
  await expect(page.getByText("History days").first()).toBeVisible();
  await expect(page.getByText("NOT READY").first()).toBeVisible();
});

test("full trace opens on a consented lead", async ({ page, request }) => {
  const token = await apiLogin(request);
  await request.patch(`${API}/api/v1/autonomy/settings`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { enabled: true },
  });
  const accounts = await request.get(`${API}/api/v1/accounts`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const accountId = ((await accounts.json()).data as { id: string; name: string }[]).find(
    (row) => row.name === "Meridian Bank",
  )?.id;
  const created = await request.post(`${API}/api/v1/leads`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      first_name: "Trace",
      last_name: "Pilot",
      email: `trace.pilot.${Date.now()}@meridianbank.example`,
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
  const leadId = (await created.json()).data.id as string;
  await uiLogin(page);
  await page.goto(`/leads/${leadId}`);
  await expect(page.getByTestId("view-full-trace")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("view-full-trace").click();
  await expect(page.getByTestId("full-trace")).toBeVisible();
});

test("mapping unlink and recalc is available after confirm", async ({ page, request }) => {
  const token = await apiLogin(request);
  const auth = { Authorization: `Bearer ${token}` };
  const stamp = Date.now();
  const domain = `pilotmap${stamp}.example`;
  const account = await request.post(`${API}/api/v1/accounts`, {
    headers: auth,
    data: { name: `Pilot Map ${stamp}`, industry: "bfsi", domain },
  });
  const accountId = (await account.json()).data.id as string;
  const opp = await request.post(`${API}/api/v1/opportunities`, {
    headers: auth,
    data: { account_id: accountId, name: `Pilot Map ${stamp} Deal`, stage: "commit", amount: "12000", probability: 90 },
  });
  const oppId = (await opp.json()).data.id as string;
  const won = await request.post(`${API}/api/v1/opportunities/${oppId}/close-won`, { headers: auth });
  expect(won.ok()).toBeTruthy();
  const connectors = await request.get(`${API}/api/v1/integrations/connectors`, { headers: auth });
  const usage = ((await connectors.json()).data as { provider: string; webhook_url: string }[]).find(
    (row) => row.provider === "usage",
  );
  expect(usage?.webhook_url).toBeTruthy();
  const secret = process.env.INTEGRATIONS_WEBHOOK_SECRET || process.env.SECRET_KEY || "change-me-to-a-long-random-string";
  const body = JSON.stringify({
    external_id: `pilot-map-${stamp}`,
    event_type: "user.active",
    account_name: `Pilot Map ${stamp}`,
    account_external_id: `ext-pilot-${stamp}`,
    user_id: "pilot-mapper",
  });
  const signature = createHmac("sha256", secret).update(body).digest("hex");
  await request.post(`${API}${usage?.webhook_url}`, {
    headers: { "X-Webhook-Signature": signature, "Content-Type": "application/json" },
    data: body,
  });
  await uiLogin(page);
  await page.goto("/admin/integrations");
  await expect(page.getByTestId("entity-mappings")).toBeVisible();
  const confirm = page.getByRole("button", { name: "Confirm" }).first();
  if (await confirm.isVisible()) {
    await confirm.click();
  }
  await page.getByRole("button", { name: "Unlink and recalc" }).first().click();
  await expect(page.getByText("unlinked").first()).toBeVisible({ timeout: 15000 });
});
