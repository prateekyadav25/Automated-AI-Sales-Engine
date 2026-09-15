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

test("closed won customer appears with automation and renewal", async ({ page, request }) => {
  const token = await apiLogin(request);
  const auth = { Authorization: `Bearer ${token}` };
  await request.patch(`${API}/api/v1/autonomy/settings`, {
    headers: auth,
    data: {
      enabled: true,
      customer_health_enabled: true,
      renewal_enabled: true,
      expansion_enabled: true,
      advocacy_enabled: true,
      customer_success_enabled: true,
    },
  });
  const stamp = Date.now();
  const account = await request.post(`${API}/api/v1/accounts`, {
    headers: auth,
    data: { name: `Post Sale E2E ${stamp}`, industry: "bfsi" },
  });
  expect(account.ok()).toBeTruthy();
  const accountId = (await account.json()).data.id as string;
  const opp = await request.post(`${API}/api/v1/opportunities`, {
    headers: auth,
    data: { account_id: accountId, name: `Post Sale E2E ${stamp} Deal`, stage: "commit", amount: "88000", probability: 90 },
  });
  expect(opp.ok()).toBeTruthy();
  const oppId = (await opp.json()).data.id as string;
  const won = await request.post(`${API}/api/v1/opportunities/${oppId}/close-won`, { headers: auth });
  expect(won.ok()).toBeTruthy();
  const customerId = (await won.json()).data.id as string;

  await uiLogin(page);
  await page.goto("/customers");
  await expect(page.getByRole("heading", { name: "Customers" })).toBeVisible();
  await expect(page.getByText(`Post Sale E2E ${stamp}`)).toBeVisible();
  await page.goto(`/customers/${customerId}`);
  await expect(page.getByText("Customer 360")).toBeVisible();
  await expect(page.getByTestId("customer-automation")).toBeVisible();
  await expect(page.getByText("Onboarding", { exact: true })).toBeVisible();
  await expect(page.getByText("Kickoff").first()).toBeVisible();

  await page.goto("/automation/runs");
  await expect(page.getByRole("heading", { name: "Autopilot" })).toBeVisible();
  await expect(page.getByText(/Onboarding started|Customer created|Handoff package created/).first()).toBeVisible();
  await expect(page.getByTestId("lane-succeed")).toBeVisible();

  await page.goto("/renewals");
  await expect(page.getByRole("heading", { name: "Renewals" })).toBeVisible();
  await expect(page.getByText(`Post Sale E2E ${stamp}`)).toBeVisible();
});
