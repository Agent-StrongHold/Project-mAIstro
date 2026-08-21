import { test as base, expect } from "@playwright/test";

const test = base.extend<{ setupDone: boolean }>({
  setupDone: [async ({ page }, use) => {
    await page.goto("/chat");
    const body = await page.textContent("body");
    if (body?.includes("Setup") || body?.includes("First boot")) {
      await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
      await page.locator("button", { hasText: "next" }).click();
      await page.locator("text=Beast").first().click();
      await page.locator("button", { hasText: "next" }).click();
      await page.locator("button", { hasText: "next" }).click();
      await page.locator("button", { hasText: "launch the hive" }).click();
      await page.waitForURL(/\/(chat)?/, { timeout: 15000 }).catch(() => {});
    }
    await use(true);
  }, { auto: true }],
});

export { test, expect };
