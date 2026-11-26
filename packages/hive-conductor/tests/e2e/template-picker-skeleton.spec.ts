/**
 * The template picker's loading skeleton is actually visible (#1421).
 *
 * `TemplatePicker.tsx` rendered `<div className="skeleton skeleton-card" />`
 * while its `/v1/dashboard/demos` fetch was in flight, but neither
 * `.skeleton` nor `.skeleton-card` had a matching CSS rule anywhere in the
 * stylesheet -- the element existed in the DOM but had no size, no
 * background, nothing to render. The loading state was an invisible div, not
 * a skeleton. Both classes now resolve to real rules (reusing the pulse
 * animation `.skeleton-block`/`.skeleton-nav-icon` already use), so the
 * placeholder actually occupies space and pulses while templates load.
 */

import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
});

test.afterAll(async () => {
  await context.close();
});

test("the template picker's skeleton has real size while templates load", async () => {
  // Slow the fetch so the loading state has time to be observed, the same
  // way a real slow link would.
  await page.route("**/v1/dashboard/demos", async (route) => {
    await new Promise((r) => setTimeout(r, 400));
    await route.continue();
  });

  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "📂 Templates", exact: true }).click();

  const skeleton = page.locator(".skeleton.skeleton-card");
  await expect(skeleton).toBeVisible({ timeout: 5000 });
  const box = await skeleton.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.height).toBeGreaterThan(0);
  expect(box!.width).toBeGreaterThan(0);

  await page.unroute("**/v1/dashboard/demos");
});
