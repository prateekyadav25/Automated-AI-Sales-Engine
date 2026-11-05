import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const GROWTH = `${API}/api/v1/social-growth`;
const PASSWORD = "Agrarian!Demo1";
const VISITOR_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";

type Account = { id: string; platform: string; provenance: string; status: string };
type Item = { id: string; platform: string; format: string; status: string; blocker: string };
type Asset = { mime: string; preview_url: string; width: number | null; height: number | null; quality_state: string };
type Creative = { id: string; status: string; quality_state: string; link_url: string; caption: string; assets: Asset[] };

const tokens = new Map<string, string>();

async function token(request: APIRequestContext, email: string) {
  const cached = tokens.get(email);
  if (cached) return cached;
  const response = await request.post(`${API}/api/v1/auth/login`, { data: { email, password: PASSWORD } });
  expect(response.ok()).toBeTruthy();
  const value = (await response.json()).data.access_token as string;
  tokens.set(email, value);
  return value;
}

async function call<T>(request: APIRequestContext, auth: string, method: "GET" | "POST" | "PUT", path: string, data?: unknown): Promise<T> {
  const response = await request.fetch(`${GROWTH}${path}`, { method, headers: { Authorization: `Bearer ${auth}` }, data });
  expect(response.ok(), `${method} ${path} returned ${response.status()}: ${await response.text()}`).toBeTruthy();
  return (await response.json()).data as T;
}

async function uiLogin(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/");
}

async function fixtureAccount(request: APIRequestContext, auth: string, platform: string): Promise<Account> {
  const existing = await call<Account[]>(request, auth, "GET", "/accounts");
  const found = existing.find((row) => row.platform === platform && row.provenance === "fixture" && row.status !== "disconnected");
  if (found) return found;
  return (await call<{ account: Account }>(request, auth, "POST", "/accounts/fixture", { platform, name: `Northwind ${platform} rehearsal` })).account;
}

test.describe.configure({ mode: "serial" });

let page: Page;

test.beforeAll(async ({ browser }, testInfo) => {
  page = await browser.newPage({ baseURL: testInfo.project.use.baseURL });
  await uiLogin(page, "admin@agrayian.demo");
});

test.afterAll(async () => {
  await page.close();
});

test("the command centre starts with live Meta calls and automation off", async () => {
  await page.goto("/growth");
  await expect(page.getByRole("heading", { name: "Social Growth Command Center" })).toBeVisible();
  await expect(page.getByText("Live Meta calls are off in this deployment")).toBeVisible();
  await expect(page.getByText("Automation is off for this workspace")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Social growth sections" })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("growth-command-center.png"), fullPage: true });
});

test("facts, fixture accounts, strategy, calendar, creative, review, and attribution run without Meta", async ({ request, browser }) => {
  test.setTimeout(240_000);
  const stamp = Date.now();
  const admin = await token(request, "admin@agrayian.demo");

  const facts: string[] = [];
  for (const [category, statement, source] of [
    ["service", "Refrigerated trucking for food and pharma loads.", "https://northwind.example/services"],
    ["service", "Same-day dry freight between Pune and Mumbai.", "https://northwind.example/services"],
    ["product", "Every load is visible on a live map.", "https://northwind.example/"],
    ["claim", "Trusted by 120 manufacturers since 2014.", "https://northwind.example/about"],
  ]) {
    const result = await call<{ fact: { id: string; state: string } }>(request, admin, "POST", "/brand/facts", { category, statement, source_url: source, evidence: statement, approve: true });
    expect(result.fact.state).toBe("approved");
    facts.push(result.fact.id);
  }
  const instagram = await fixtureAccount(request, admin, "instagram");
  const facebook = await fixtureAccount(request, admin, "facebook");
  const formResponse = await request.post(`${API}/api/v1/acquisition/form-keys`, { headers: { Authorization: `Bearer ${admin}` }, data: { name: `Growth E2E ${stamp}` } });
  expect(formResponse.ok()).toBeTruthy();
  const formId = (await formResponse.json()).data.id as string;

  const draft = await call<{ id: string }>(request, admin, "PUT", "/strategy", {
    objective: "More enquiries from manufacturers in Pune.",
    optimization_metric: "reach",
    pillars: [
      { key: "offer", name: "What we move", fact_ids: [facts[0], facts[1]] },
      { key: "proof", name: "Proof", fact_ids: [facts[2], facts[3]] },
    ],
    audiences: ["Plant managers in Pune"],
    cadence: { [instagram.id]: { formats: { image: 2, carousel: 1, reel: 1 } }, [facebook.id]: { formats: { image: 2 } } },
    call_to_action: "Ask for a route quote",
    destination_kind: "form",
    destination_form_key_id: formId,
    auto_create: true,
    auto_schedule: false,
    horizon_days: 30,
  });
  const approved = await call<{ status: string }>(request, admin, "POST", `/strategy/${draft.id}/approve`);
  expect(approved.status).toBe("approved");
  const plan = await call<{ status: string }>(request, admin, "POST", "/calendar/plan");
  expect(plan.status).toBe("planned");

  const calendar = await call<{ items: Item[] }>(request, admin, "GET", "/calendar");
  const planned = calendar.items.filter((row) => row.platform === "instagram" && row.status === "planned");
  const imageSlot = planned.find((row) => row.format === "image");
  const reelSlot = planned.find((row) => row.format === "reel");
  expect(imageSlot, "an Instagram image slot is planned under the new version").toBeTruthy();
  expect(reelSlot, "an Instagram Reel slot is planned under the new version").toBeTruthy();

  const still = await call<Creative>(request, admin, "POST", `/calendar/${imageSlot!.id}/creative`);
  expect(still.quality_state).toBe("passed");
  expect(still.link_url).toContain("/api/v1/public/r/");
  expect(still.assets[0]?.mime).toBe("image/jpeg");
  const reel = await call<Creative>(request, admin, "POST", `/calendar/${reelSlot!.id}/creative`);
  const video = reel.assets.find((asset) => asset.mime === "video/mp4");
  expect(video, "the Reel has a rendered MP4").toBeTruthy();
  expect([video?.width, video?.height]).toEqual([1080, 1920]);
  expect(video?.quality_state).toBe("passed");

  await page.goto("/growth/brand");
  await expect(page.getByRole("heading", { name: "Brand intelligence" })).toBeVisible();
  await expect(page.getByText("Trusted by 120 manufacturers since 2014.").first()).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("growth-brand.png"), fullPage: true });
  await page.goto("/growth/accounts");
  await expect(page.getByRole("heading", { name: "Connected accounts", exact: true }).first()).toBeVisible();
  await expect(page.getByText("Fixture (not live)").first()).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("growth-accounts.png"), fullPage: true });

  await page.goto("/growth/calendar");
  await expect(page.getByRole("heading", { name: "Strategy and rolling calendar" })).toBeVisible();
  await expect(page.getByTestId("growth-calendar-item").first()).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("growth-calendar.png"), fullPage: true });

  await page.goto("/growth/studio");
  const card = page.locator(`[data-creative-id="${still.id}"]`);
  await expect(card).toBeVisible();
  const preview = card.locator("img").first();
  await expect(preview).toBeVisible();
  await expect.poll(() => preview.evaluate((node) => (node as HTMLImageElement).naturalWidth)).toBe(1080);
  await expect(page.locator(`[data-creative-id="${reel.id}"] video`)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("growth-studio.png"), fullPage: true });
  await card.getByRole("button", { name: "Approve creative" }).click();
  await expect(card).toHaveCount(0);
  await expect.poll(async () => (await call<Creative>(request, admin, "GET", `/creatives/${still.id}`)).status).toBe("approved");

  await page.goto("/growth/calendar");
  const slot = page.locator(`[data-item-id="${imageSlot!.id}"]`);
  await slot.getByRole("button", { name: "Schedule" }).click();
  await expect(slot.getByText("Waiting for publish approval in the decision inbox.")).toBeVisible();
  const attempt = await call<{ published: boolean; detail: string }>(request, admin, "POST", `/calendar/${imageSlot!.id}/publish`);
  expect(attempt.published).toBe(false);
  expect(attempt.detail).toContain("Nothing was published");
  const publications = await call<{ provenance: string }[]>(request, admin, "GET", "/publications");
  expect(publications.filter((row) => row.provenance === "live")).toHaveLength(0);

  const before = await call<{ traffic: { first_party_clicks: number; bot_clicks_excluded: number }; enquiries: { count: number } }>(request, admin, "GET", "/attribution?range=1d");
  const crawler = await request.get(still.link_url, { headers: { "User-Agent": "facebookexternalhit/1.1" }, maxRedirects: 0 });
  expect(crawler.status()).toBe(302);
  const visitorContext = await browser.newContext({ userAgent: VISITOR_AGENT });
  const visitor = await visitorContext.newPage();
  await visitor.goto(still.link_url);
  await expect(visitor).toHaveURL(/\/capture\/[^?]+\?.*growth=/);
  await visitor.getByLabel("First name").fill("Meera");
  await visitor.getByLabel("Last name").fill(`Visitor ${stamp}`);
  await visitor.getByLabel("Work email").fill(`meera.${stamp}@example.com`);
  await visitor.getByLabel("What do you want?").fill("A route quote for chilled loads from Pune.");
  await visitor.getByLabel("I agree to be contacted about this request.").check();
  await visitor.getByRole("button", { name: "Submit request" }).click();
  await expect(visitor.getByText("Received.")).toBeVisible();
  await visitorContext.close();
  const after = await call<{ traffic: { first_party_clicks: number; bot_clicks_excluded: number }; enquiries: { count: number } }>(request, admin, "GET", "/attribution?range=1d");
  expect(after.traffic.first_party_clicks).toBe(before.traffic.first_party_clicks + 1);
  expect(after.traffic.bot_clicks_excluded).toBe(before.traffic.bot_clicks_excluded + 1);
  expect(after.enquiries.count).toBe(before.enquiries.count + 1);

  await page.goto("/growth/performance");
  await page.getByLabel("Period").selectOption("1d");
  await expect(page.getByText("Fixture evidence").first()).toBeVisible();
  await expect(page.getByText("No account reading is stored for this period. Values are unavailable, not zero.").first()).toBeVisible();
  await expect(page.getByText("automated visits excluded")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("growth-performance.png"), fullPage: true });
});

test("read-only users can look but cannot plan, connect, or approve", async ({ page: readerPage, request }) => {
  const reader = await token(request, "readonly@agrayian.demo");
  const headers = { Authorization: `Bearer ${reader}` };
  expect((await request.get(`${GROWTH}/overview`, { headers })).ok()).toBeTruthy();
  expect((await request.post(`${GROWTH}/calendar/plan`, { headers })).status()).toBe(403);
  expect((await request.post(`${GROWTH}/accounts/fixture`, { headers, data: { platform: "instagram" } })).status()).toBe(403);
  expect((await request.post(`${GROWTH}/grants`, { headers, data: { platform: "instagram", volume_cap: 1, days: 1 } })).status()).toBe(403);
  await uiLogin(readerPage, "readonly@agrayian.demo");
  await readerPage.goto("/growth/calendar");
  await expect(readerPage.getByRole("heading", { name: "Strategy and rolling calendar" })).toBeVisible();
  await expect(readerPage.getByRole("button", { name: "Plan the next 30 days" })).toHaveCount(0);
  await readerPage.goto("/growth/studio");
  await expect(readerPage.getByRole("heading", { name: "Creative studio" })).toBeVisible();
  await expect(readerPage.getByRole("button", { name: "Approve creative" })).toHaveCount(0);
  await expect(readerPage.getByRole("button", { name: "Create grant" })).toHaveCount(0);
});

test("another workspace sees none of this workspace's growth records", async ({ request }) => {
  const admin = await token(request, "admin@agrayian.demo");
  const other = await token(request, "admin@northline.demo");
  const calendar = await call<{ items: Item[] }>(request, admin, "GET", "/calendar");
  const owned = calendar.items.find((row) => row.status !== "planned") ?? calendar.items[0];
  expect(owned, "the first workspace has calendar items").toBeTruthy();
  const theirs = await call<{ items: Item[] }>(request, other, "GET", "/calendar");
  expect(theirs.items.some((row) => row.id === owned!.id)).toBeFalsy();
  const headers = { Authorization: `Bearer ${other}` };
  expect((await request.post(`${GROWTH}/calendar/${owned!.id}/creative`, { headers })).status()).toBe(404);
  const accounts = await call<Account[]>(request, admin, "GET", "/accounts");
  expect((await request.post(`${GROWTH}/accounts/${accounts[0]!.id}/verify`, { headers })).status()).toBe(404);
});
