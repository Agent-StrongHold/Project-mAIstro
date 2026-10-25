import { expect, test, type Page } from "@playwright/test";

// The live wizard is five steps (Hive -> Hardware -> Accounts -> Modules ->
// Confirm). The Accounts step requires admin + daily-user credentials before
// "next" enables, so every flow that reaches Optional modules walks it here.
// #287: when no gateway answers, the wizard keeps "next" locked until the
// unverified-availability acknowledgement is checked, so — like
// tests/e2e/session.ts — wait briefly for the checkbox and check it when it
// renders. A discovered catalog never renders it and this is a no-op there.
async function acknowledgeUnverifiedModels(page: Page) {
  const ack = page.getByTestId("unverified-ack").getByRole("checkbox");
  const visible = await ack
    .waitFor({ state: "visible", timeout: 10000 })
    .then(() => true)
    .catch(() => false);
  if (visible) await ack.check();
}

async function reachModulesStep(page: Page) {
  await page.goto("/");
  await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
  await acknowledgeUnverifiedModels(page);
  await page.locator("button", { hasText: "next" }).click();
  await page.getByText("Beast", { exact: true }).click();
  await page.locator("button", { hasText: "next" }).click();
  await page.getByRole("textbox", { name: "Admin password" }).fill("admin-password-1");
  await page.getByRole("textbox", { name: "Daily user username" }).fill("daily-user");
  await page.getByRole("textbox", { name: "Daily user password" }).fill("daily-password-1");
  await page.locator("button", { hasText: "next" }).click();
  await expect(page.getByText("Optional modules")).toBeVisible();
}

test.describe("Setup Wizard", () => {
  test("shows setup wizard on first boot", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("🐝 Hive Conductor")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/First boot/)).toBeVisible();
  });

  test("step indicators show the wizard steps", async ({ page }) => {
    await page.goto("/");
    // The step strip is the only wizard-surface element with a 1px bottom rule;
    // its labels render as "1Hive…5Confirm", so assert on the strip's text.
    const strip = page.locator('div[style*="border-bottom: 1px solid var(--rule)"]');
    await expect(strip).toHaveCount(1);
    for (const label of ["Hive", "Hardware", "Accounts", "Modules", "Confirm"]) {
      await expect(strip).toContainText(label);
    }
  });

  test("can type conductor name and proceed", async ({ page }) => {
    await page.goto("/");
    const input = page.locator('input[placeholder="Hive Conductor"]');
    await expect(input).toBeVisible();
    await input.fill("Test Hive");
    await acknowledgeUnverifiedModels(page);
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.getByText("Pick your hardware tier")).toBeVisible();
  });

  test("can select hardware preset", async ({ page }) => {
    await page.goto("/");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await acknowledgeUnverifiedModels(page);
    await page.locator("button", { hasText: "next" }).click();
    await page.getByText("Beast", { exact: true }).click();
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.getByText("Create user accounts")).toBeVisible();
  });

  test("can toggle modules and proceed", async ({ page }) => {
    await reachModulesStep(page);
    await page.getByText("Home Automation", { exact: true }).click();
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.getByText("Confirm configuration")).toBeVisible();
  });

  test("does not offer crypto identity when the runtime is unavailable", async ({ page }) => {
    await page.route("**/health", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ identity: { status: "unavailable", reason: "identity_runtime_missing" } }),
    }));
    await reachModulesStep(page);

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
    await reachModulesStep(page);

    const cryptoCard = page.locator(".card").filter({ hasText: "Crypto Identity" });
    await expect(cryptoCard).toContainText("unavailable in this deployment; no action offered");
    await expect(cryptoCard.getByRole("button", { name: "Toggle Crypto Identity" })).toBeDisabled();
  });

  test("can complete setup and unlock the hive", async ({ page }) => {
    await reachModulesStep(page);
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.getByText("Confirm configuration")).toBeVisible();
    await page.locator("button", { hasText: "launch the hive" }).click();
    // The wizard seeds the declared module default (crypto identity), so when
    // the deployment can serve an identity root, completing setup shows the
    // once-only recovery phrase first (#443). With identity unavailable the
    // seeded set is empty and the app auto-logs the daily user straight in.
    const seed = page.getByText("Recovery Seed Phrase");
    try {
      await expect(seed).toBeVisible({ timeout: 5000 });
      await page.getByLabel("I have written these words down and stored them safely").check();
      await page.locator("button", { hasText: "enter the hive" }).click();
    } catch {
      // No identity root on this deployment — no mnemonic screen.
    }
    await expect(page.getByText("Live Operations")).toBeVisible({ timeout: 20000 });
  });
});
