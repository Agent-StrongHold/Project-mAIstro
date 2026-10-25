/**
 * Capabilities shell (#2273): primary nav lands on the unified surface over
 * `/v1/capabilities`, and legacy Agents/Integrations stay out of the rail.
 */
import { expect, test } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  await setupIfNeeded(page);
  await loginAsPM(page);
});

test("Capabilities is reachable from the icon rail and loads the API surface", async ({ page }) => {
  await page.goto("/dashboard");
  const link = page.locator(".icon-sidebar").getByRole("link", { name: "Capabilities", exact: true });
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL("**/capabilities");
  await expect(page.getByRole("heading", { name: "Capabilities", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Re-discover providers" })).toBeVisible();
});

test("Agents and Integrations stay out of primary nav after Capabilities cutover", async ({ page }) => {
  await page.goto("/capabilities");
  const rail = page.locator(".icon-sidebar");
  await expect(rail.getByRole("link", { name: "Agents", exact: true })).toHaveCount(0);
  await expect(rail.getByRole("link", { name: "Integrations", exact: true })).toHaveCount(0);
  await expect(rail.getByRole("link", { name: "Topology", exact: true })).toHaveCount(0);
});
