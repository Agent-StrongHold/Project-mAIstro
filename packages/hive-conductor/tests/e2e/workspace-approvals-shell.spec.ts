/**
 * Approvals projection (#2278 / Parity P-1): nav reaches the surface that
 * calls the same capability + HITL APIs as CLI.
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

test("Approvals is reachable from the icon rail and shows both queues", async ({ page }) => {
  await page.goto("/dashboard");
  const link = page.locator(".icon-sidebar").getByRole("link", { name: "Approvals", exact: true });
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL("**/approvals");
  await expect(page.getByRole("heading", { name: "Approvals", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Capability inbox" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "HITL (paused Runs)" })).toBeVisible();
});
