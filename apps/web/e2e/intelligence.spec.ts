import { expect, test, type Page } from "@playwright/test";

async function uiLogin(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@agrayian.demo");
  await page.getByLabel("Password").fill("Agrarian!Demo1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/");
}

test("models page shows readiness, empty datasets, no trained model, and no challenger", async ({ page }) => {
  await uiLogin(page);
  await page.goto("/models");
  await expect(page.getByTestId("readiness-heading")).toBeVisible();
  await expect(page.getByRole("row", { name: /LEAD_CONVERSION/ })).toContainText("DATA_COLLECTION");
  await expect(page.getByTestId("datasets-heading")).toBeVisible();
  await expect(page.getByText("No datasets")).toBeVisible();
  await expect(page.getByTestId("registry-heading")).toBeVisible();
  await expect(page.getByText("NO TRAINED MODEL")).toBeVisible();
  await expect(page.getByTestId("shadow-indicator")).toContainText("Challenger: none");
  await expect(page.getByRole("cell", { name: "null" }).first()).toBeVisible();
});
