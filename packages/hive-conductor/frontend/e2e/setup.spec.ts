import { test, expect } from "@playwright/test";

// Selectors mirror the shipped wizard (src/pages/Setup.tsx): five steps —
// Hive, Hardware, Accounts, Modules, Confirm — where the Accounts step
// requires the admin and daily-user credentials before "next" enables.
// Provisioning ends with an auto-login as the DAILY USER, so the post-setup
// assertions below run as that role, not as the break-glass admin (#336).

const ADMIN_PASSWORD = "break-glass-passphrase-1";
const USER_PASSWORD = "daily-driver-passphrase-1";

test.describe("Setup Wizard", () => {
  test("shows setup wizard on first boot", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("text=First boot")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=Hive").first()).toBeVisible();
  });

  test("step indicators show all five steps", async ({ page }) => {
    await page.goto("/");
    for (const step of ["Hive", "Hardware", "Accounts", "Modules", "Confirm"]) {
      await expect(page.getByText(step).first()).toBeVisible();
    }
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
    await expect(page.locator("text=Create user accounts")).toBeVisible();
  });

  test("accounts step requires credentials before proceeding", async ({ page }) => {
    await page.goto("/");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await page.locator("button", { hasText: "next" }).click();
    await page.locator("text=Beast").click();
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.locator("text=Create user accounts")).toBeVisible();
    // The wizard demands both credentials itself: next stays disabled until
    // the admin password, the daily username, and the daily password land.
    const next = page.locator("button", { hasText: "next" });
    await expect(next).toBeDisabled();
    await page.getByRole("textbox", { name: "Admin password" }).fill(ADMIN_PASSWORD);
    await page.getByRole("textbox", { name: "Daily user username" }).fill("user");
    await expect(next).toBeDisabled();
    await page.getByRole("textbox", { name: "Daily user password" }).fill(USER_PASSWORD);
    await expect(next).toBeEnabled();
    await next.click();
    await expect(page.locator("text=Optional modules")).toBeVisible();
  });

  test("can complete setup and unlock the hive as the daily user", async ({ page }) => {
    await page.goto("/");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await page.locator("button", { hasText: "next" }).click();
    await page.locator("text=Beast").click();
    await page.locator("button", { hasText: "next" }).click();
    await page.getByRole("textbox", { name: "Admin password" }).fill(ADMIN_PASSWORD);
    await page.getByRole("textbox", { name: "Daily user username" }).fill("user");
    await page.getByRole("textbox", { name: "Daily user password" }).fill(USER_PASSWORD);
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.locator("text=Optional modules")).toBeVisible();
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.locator("text=Confirm configuration")).toBeVisible();
    await page.locator("button", { hasText: "launch the hive" }).click();
    // Setup auto-logs-in as the daily user and redirects to the app index:
    // the chat surface must be reachable for that account, never a 403 wall.
    await expect(page.locator("text=Hive Conductor").first()).toBeVisible({
      timeout: 15000,
    });
  });
});
