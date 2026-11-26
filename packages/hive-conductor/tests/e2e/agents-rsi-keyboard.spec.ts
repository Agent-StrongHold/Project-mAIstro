/**
 * RSI Stop keyboard contract (#370), plus confirmation that /agents no longer
 * hosts the retired Agents builder (#2273 — page deleted; URL redirects).
 *
 * The Agent builder / Intent Map keyboard journeys lived on Agents.tsx and
 * left with that module. RSI Stop remains here because it is still a shipped
 * surface (#373 gates it behind PermissionBoundary("rsi.execute")).
 */

import AxeBuilder from "@axe-core/playwright";
import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { loginAsAdmin, loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
// #373: /rsi sits behind PermissionBoundary("rsi.execute"), so the Stop-keyboard
// contract is walked under the admin account — the principal that holds
// effective rsi.execute without an elevation whose grant the test hive caps at
// 8 seconds (HIVE_ELEVATION_TTL_SECONDS in docker-compose.test.yml). The
// daily-user navigation contract for the gated entry is pinned by
// authorization.spec.ts and navigation-coverage.spec.ts.
let rsiContext: BrowserContext;
let rsiPage: Page;

const RUN_ID = "run-kbd-370";

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
});

test.afterAll(async () => {
  await context.close();
  await rsiContext?.close();
});

async function scanMain(p: Page) {
  const results = await new AxeBuilder({ page: p })
    .include("main")
    .disableRules(["color-contrast"])
    .analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
}

test("/agents redirects to Capabilities — Agents builder module is not revived (#2273)", async () => {
  await page.goto("/agents", { waitUntil: "domcontentloaded" });
  await page.waitForURL("**/capabilities");
  await expect(page.getByRole("heading", { name: "Capabilities", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "The Hive", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Builder", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Intent Map", exact: true })).toHaveCount(0);
});

test("a running RSI run's Stop is its own button and Enter sends the stop", async ({ browser }) => {
  // #373: RSI is an authority-gated surface, so this walk runs in its own
  // admin session (see the rsiPage note above); the mocked RSI endpoints
  // travel with that page, not with the PM session the roster test uses.
  rsiContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  await rsiContext.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
  rsiPage = await rsiContext.newPage();
  await setupIfNeeded(rsiPage);
  await loginAsAdmin(rsiPage);
  const run = {
    run_id: RUN_ID,
    mode: "autorun",
    status: "running",
    started_at: "2026-09-26T00:00:00Z",
    ended_at: null,
    cycles: 3,
    promotions: 1,
    last_error: null,
    summary: null,
    config: {},
    report_dir: null,
  };
  await rsiPage.route("**/v1/rsi/status", (r) => r.fulfill({ json: { available: true, active_runs: 1, total_runs: 1 } }));
  await rsiPage.route("**/v1/rsi/runs", (r) => r.fulfill({ json: [run] }));
  await rsiPage.route("**/v1/rsi/models", (r) => r.fulfill({ json: { models: [] } }));
  await rsiPage.route("**/v1/rsi/test-profiles", (r) => r.fulfill({ json: { profiles: [] } }));
  await rsiPage.route(`**/v1/rsi/runs/${RUN_ID}/reviews`, (r) => r.fulfill({ json: { kept: [], flagged: [] } }));
  await rsiPage.route(`**/v1/rsi/runs/${RUN_ID}/rlphd`, (r) => r.fulfill({ json: {} }));
  const stops: string[] = [];
  await rsiPage.route(`**/v1/rsi/runs/${RUN_ID}/stop`, async (r) => {
    stops.push(r.request().method());
    await r.fulfill({ json: { ok: true } });
  });

  await rsiPage.goto("/rsi", { waitUntil: "domcontentloaded" });
  const row = rsiPage.getByRole("button", { name: `running ${RUN_ID} 1/3 promoted`, exact: true });
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect(row).toHaveAttribute("aria-pressed", "false");

  // Stop first, with the row unselected: if the stop bubbled into the row it
  // would select it.
  await row.focus();
  await rsiPage.keyboard.press("Tab");
  const stop = rsiPage.getByRole("button", { name: `Stop run ${RUN_ID}`, exact: true });
  await expect(stop).toBeFocused();
  await rsiPage.keyboard.press("Enter");
  await expect.poll(() => stops).toEqual(["POST"]);
  await expect(row).toHaveAttribute("aria-pressed", "false");

  await rsiPage.keyboard.press("Shift+Tab");
  await expect(row).toBeFocused();
  await rsiPage.keyboard.press("Enter");
  await expect(row).toHaveAttribute("aria-pressed", "true");

  expect(await rsiPage.locator("button button, button a[href], button input, button select, button [role=button]").count()).toBe(0);
  const nested = await new AxeBuilder({ page: rsiPage }).withRules(["nested-interactive"]).analyze();
  expect(nested.violations).toEqual([]);
  await scanMain(rsiPage);
  expect(stops).toEqual(["POST"]);
});
