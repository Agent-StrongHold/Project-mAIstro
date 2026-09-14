import { test, expect } from "@playwright/test";

test.describe("Setup Wizard", () => {
  test("shows setup wizard on first boot", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("text=Hive Conductor Setup")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=First boot")).toBeVisible();
  });

  test("step indicators show 4 steps", async ({ page }) => {
    await page.goto("/");
    // The four step labels are the assertion; a `.page-header + div > div`
    // locator was built here for a count check that was never written. It is
    // not restored as `toHaveCount(4)` because that selector also matches the
    // header's own children, so the count it would assert is unverified.
    await expect(page.locator("text=Hive")).toBeVisible();
    await expect(page.locator("text=Hardware")).toBeVisible();
    await expect(page.locator("text=Modules")).toBeVisible();
    await expect(page.locator("text=Confirm")).toBeVisible();
  });

  test("can type conductor name and proceed", async ({ page }) => {
    await page.goto("/");
    const input = page.locator('input[placeholder="Hive Conductor"]');
    await expect(input).toBeVisible();
    await input.fill("Test Hive");
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.locator("text=Pick your hardware tier")).toBeVisible();
  });

  test("can select hardware preset", async ({ page }) => {
    await page.goto("/");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.locator("text=Pick your hardware tier")).toBeVisible();
    await page.locator("text=Beast").click();
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.locator("text=Optional modules")).toBeVisible();
  });

  test("can toggle modules and proceed", async ({ page }) => {
    await page.goto("/");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await page.locator("button", { hasText: "next" }).click();
    await page.locator("text=Beast").click();
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.locator("text=Crypto Identity")).toBeVisible();
    await page.locator("text=Home Automation").click();
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.locator("text=Confirm configuration")).toBeVisible();
  });

  test("does not offer crypto identity when the runtime is unavailable", async ({ page }) => {
    await page.route("**/health", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ identity: { status: "unavailable", reason: "identity_runtime_missing" } }),
    }));
    await page.goto("/");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await page.locator("button", { hasText: "next" }).click();
    await page.locator("text=Beast").click();
    await page.locator("button", { hasText: "next" }).click();

    const cryptoCard = page.locator(".card").filter({ hasText: "Crypto Identity" });
    await expect(cryptoCard).toContainText("unavailable in this deployment; no action offered");
    await expect(cryptoCard.getByRole("button", { name: "Toggle Crypto Identity" })).toBeDisabled();
  });

  test("does not offer crypto identity when the deployment is misconfigured", async ({ page }) => {
    await page.route("**/health", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ identity: { status: "misconfigured", reason: "identity_seed_missing" } }),
    }));
    await page.goto("/");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await page.locator("button", { hasText: "next" }).click();
    await page.locator("text=Beast").click();
    await page.locator("button", { hasText: "next" }).click();

    const cryptoCard = page.locator(".card").filter({ hasText: "Crypto Identity" });
    await expect(cryptoCard).toContainText("unavailable in this deployment; no action offered");
    await expect(cryptoCard.getByRole("button", { name: "Toggle Crypto Identity" })).toBeDisabled();
  });

  test("can complete setup and unlock the hive", async ({ page }) => {
    await page.goto("/");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await page.locator("button", { hasText: "next" }).click();
    await page.locator("text=Beast").click();
    await page.locator("button", { hasText: "next" }).click();
    await page.locator("button", { hasText: "next" }).click();
    await page.locator("button", { hasText: "launch the hive" }).click();
    await page.waitForURL(/\/(chat)?/, { timeout: 15000 });
  });
});
