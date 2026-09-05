import { expect, test } from "@playwright/test";

test("login shows Autopilot on and Approvals evidence", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@agrayian.demo");
  await page.getByLabel("Password").fill("Agrarian!Demo1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/");
  await expect(page.getByText("Autopilot", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("ON").first()).toBeVisible();
  await page.goto("/automation/runs");
  await expect(page.getByTestId("autopilot-state")).toContainText("ON");
  await expect(page.getByRole("heading", { name: "Autopilot" })).toBeVisible();
  await expect(page.getByText("Approvals waiting")).toBeVisible();
  await page.goto("/automation/approvals");
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  await expect(page.getByText("Who").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" }).first()).toBeVisible();
});
