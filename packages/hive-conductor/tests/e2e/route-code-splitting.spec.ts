/**
 * Routed pages are code-split, not bundled with the initial script (#1435).
 *
 * The 24 pages behind `AppShell`'s routes were all statically imported, so
 * visiting any one page paid for every page's JS -- a single ~600kB chunk,
 * over Vite's build warning threshold. Each is now `React.lazy`-loaded, so a
 * cold load only fetches the page it actually renders, and other pages'
 * chunks arrive only once their route is visited.
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test("a route's chunk is fetched only once its page is visited, not on cold load", async ({
  page,
}) => {
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  const scriptRequests: string[] = [];
  page.on("request", (r) => {
    if (r.resourceType() === "script" && r.url().includes("/assets/")) {
      scriptRequests.push(r.url());
    }
  });

  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Live Operations" })).toBeVisible({
    timeout: 15000,
  });
  // The Dashboard route's lazy chunk has resolved and rendered by the time
  // its heading is visible; give any in-flight request a moment to be
  // recorded rather than racing the request listener.
  await page.waitForTimeout(300);

  // The Dashboard route's own chunk loaded ...
  expect(scriptRequests.some((u) => /\/assets\/Dashboard-[^/]+\.js$/.test(u))).toBe(true);
  // ... but a page nobody has navigated to yet did not ride along with it.
  expect(scriptRequests.some((u) => /\/assets\/Settings-[^/]+\.js$/.test(u))).toBe(false);
  expect(scriptRequests.some((u) => /\/assets\/Agents-[^/]+\.js$/.test(u))).toBe(false);

  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect
    .poll(() => scriptRequests.some((u) => /\/assets\/Settings-[^/]+\.js$/.test(u)), {
      timeout: 5000,
    })
    .toBe(true);
});
