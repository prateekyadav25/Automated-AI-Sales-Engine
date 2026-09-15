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

test("provider modes and blocked configuration are visible", async ({ page, request }) => {
  const token = await apiLogin(request);
  await request.patch(`${API}/api/v1/autonomy/settings`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { enabled: true },
  });
  await uiLogin(page);
  await page.goto("/automation/runs");
  await expect(page.getByRole("heading", { name: "Autopilot" })).toBeVisible();
  await expect(page.getByTestId("provider-apify")).toBeVisible();
  await expect(page.getByTestId("provider-linkedin-ads")).toContainText("MOCK");
  await expect(page.getByTestId("provider-voice")).toContainText("MOCK");
  await page.goto("/admin/integrations");
  await expect(page.getByTestId("provider-modes")).toBeVisible();
  await expect(page.getByTestId("integration-apify")).toContainText("MOCK");
});

test("ad approval card appears after launch", async ({ page, request }) => {
  const token = await apiLogin(request);
  const auth = { Authorization: `Bearer ${token}` };
  const campaign = await request.post(`${API}/api/v1/lifecycle/campaigns`, {
    headers: auth,
    data: { name: `E2E Ads ${Date.now()}`, channel: "linkedin", budget: "400" },
  });
  expect(campaign.ok()).toBeTruthy();
  const launch = await request.post(`${API}/api/v1/lifecycle/campaigns/${(await campaign.json()).data.id}/launch`, {
    headers: auth,
  });
  expect(launch.ok()).toBeTruthy();
  await uiLogin(page);
  await page.goto("/automation/approvals");
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  await expect(page.getByText("Launch linkedin campaign").first()).toBeVisible();
});

test("voice approval card appears after dial request", async ({ page, request }) => {
  const token = await apiLogin(request);
  const auth = { Authorization: `Bearer ${token}` };
  const contact = await request.post(`${API}/api/v1/contacts`, {
    headers: auth,
    data: {
      first_name: "E2E",
      last_name: "Voice",
      email: `e2e.voice.${Date.now()}@example.com`,
      phone: "+15555550999",
      preferred_channel: "VOICE",
      consent_voice: true,
    },
  });
  expect(contact.ok()).toBeTruthy();
  const dial = await request.post(`${API}/api/v1/lifecycle/conversations/dial`, {
    headers: auth,
    data: { contact_id: (await contact.json()).data.id, consent: true },
  });
  expect(dial.ok()).toBeTruthy();
  await uiLogin(page);
  await page.goto("/automation/approvals");
  await expect(page.getByText("Dial E2E Voice").first()).toBeVisible();
});
