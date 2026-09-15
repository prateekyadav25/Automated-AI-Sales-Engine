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

test("pause resume emergency stop and dead-letter inspect", async ({ page, request }) => {
  const token = await apiLogin(request);
  await request.post(`${API}/api/v1/providers/actions`, {
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => undefined);
  await uiLogin(page);
  await page.goto("/automation/runs");
  await expect(page.getByRole("heading", { name: "Autopilot" })).toBeVisible();
  await page.getByTestId("pause-tenant").click();
  await expect(page.getByTestId("autopilot-state")).toContainText("OFF", { timeout: 15000 });
  await page.getByTestId("resume-tenant").click();
  await expect(page.getByTestId("autopilot-state")).toContainText("ON", { timeout: 15000 });
  await page.getByTestId("emergency-stop").click();
  await expect(page.getByTestId("emergency-stop-active")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("emergency-stop").click();
  await expect(page.getByTestId("dead-letter-panel").or(page.getByTestId("dead-letter-empty"))).toBeVisible();
});

test("knowledge upload retrieves after object storage", async ({ request }) => {
  const token = await apiLogin(request);
  const uploaded = await request.post(`${API}/api/v1/ai/knowledge`, {
    headers: { Authorization: `Bearer ${token}` },
    multipart: {
      title: "Playwright knowledge",
      file: {
        name: "note.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("playwright retrieval evidence"),
      },
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const sourceId = (await uploaded.json()).data.id as string;
  const downloaded = await request.get(`${API}/api/v1/ai/knowledge/${sourceId}/file`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(downloaded.ok()).toBeTruthy();
  const search = await request.get(`${API}/api/v1/ai/knowledge/search`, {
    headers: { Authorization: `Bearer ${token}` },
    params: { q: "retrieval" },
  });
  expect(search.ok()).toBeTruthy();
});
