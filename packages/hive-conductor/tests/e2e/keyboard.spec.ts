/**
 * Keyboard reachability for the Conductor primary journeys (#370).
 *
 * These run in the same live-browser harness as the rest of `tests/e2e/`, and
 * that location is deliberate: `frontend/e2e/` is executed by no workflow, so a
 * keyboard journey placed there would never run. The journeys below are the
 * regression guard for "every interactive control is reachable and operable
 * with the keyboard alone" — the click-only ratchet in
 * `frontend/scripts/check-keyboard-controls.mjs` proves the generic elements
 * are gone; this proves the replacements actually work in a browser.
 *
 * The tab-order test is the stronger half. Calling `.focus()` on a control only
 * proves it is focusable; walking the real Tab order proves it is *reachable*,
 * which is the failure a keyboard user actually feels.
 */

import { test, expect, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

const designSystems = {
  systems: [{ slug: "default", name: "Default", description: "", origin: "bundled" }],
  catalog: { available: true, cause: null, count: 1 },
  ready: true,
  cause: null,
  bundled_count: 1,
};

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
  });
  // The onboarding tour is a full-screen dialog on a fresh install; mark it
  // seen before the app's own scripts run so it cannot cover these pages.
  await context.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  page = await context.newPage();

  // The Design Studio picker is only rendered once its catalog loads. Serving a
  // deterministic catalog keeps the /cli/canvas journey independent of the
  // backend's design resources.
  await page.route("**/v1/design/skills", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/v1/design/systems", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(designSystems),
    });
  });

  await setupIfNeeded(page);
  await loginAsPM(page);
});

test.afterAll(async () => {
  await context.close();
});

/**
 * Walks the page's real Tab order and returns one descriptor per focused
 * element. Recording `focusin` instead of asserting after every press keeps the
 * cost at one keyboard press per stop rather than a round trip per stop.
 */
async function tabOrder(page: Page, maxTabs = 220): Promise<string[]> {
  await page.evaluate(() => {
    const store = window as unknown as { __tabOrder?: string[] };
    store.__tabOrder = [];
    document.addEventListener(
      "focusin",
      (event) => {
        const element = event.target as HTMLElement;
        if (!element || element === document.body) return;
        const label = (
          element.getAttribute("aria-label") ||
          (element as HTMLInputElement).labels?.[0]?.textContent ||
          element.textContent ||
          element.getAttribute("placeholder") ||
          element.tagName
        )
          .trim()
          .replace(/\s+/g, " ")
          .slice(0, 80);
        store.__tabOrder?.push(`${element.tagName}:${label}`);
      },
      true,
    );
  });

  // `domcontentloaded` pages have focus on <body>, so the first Tab starts at
  // the top of the document.
  for (let i = 0; i < maxTabs; i += 1) {
    await page.keyboard.press("Tab");
  }
  return page.evaluate(() => (window as unknown as { __tabOrder?: string[] }).__tabOrder ?? []);
}

function isReachable(order: string[], pattern: RegExp): boolean {
  return order.some((entry) => pattern.test(entry));
}

test("skip link is the first tab stop and moves focus to the main landmark", async () => {
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

  // The skip link is visually hidden with a CSS transform until focused, so
  // Chromium keeps it out of the accessibility tree and getByRole cannot find
  // it. A CSS selector sees it regardless, and focus behaves the same.
  const skip = page.locator("a.skip-link");
  await skip.waitFor({ state: "attached", timeout: 15000 });

  // Chat auto-focuses its message box on mount; the dashboard does not, so
  // dropping focus to <body> and pressing Tab starts a real walk from the top
  // of the document.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(page.locator("main#main-content")).toBeFocused();
});

test("chat model menu is operable without a pointer and returns focus", async () => {
  await page.goto("/chat", { waitUntil: "domcontentloaded" });

  const modelButton = page.getByRole("button", { name: /Current model/ });
  await expect(modelButton).toBeVisible({ timeout: 10000 });
  await modelButton.focus();
  await page.keyboard.press("Enter");

  const listbox = page.getByRole("listbox");
  await expect(listbox).toBeVisible();

  // Selecting with the keyboard must return focus to the trigger rather than
  // strand the user on <body>, which would restart the Tab walk at the top.
  const option = listbox.locator("button").first();
  await option.focus();
  await expect(option).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(listbox).toBeHidden();
  await expect(modelButton).toBeFocused();

  // Escape also closes and lands back on the trigger.
  await page.keyboard.press("Enter");
  await expect(listbox).toBeVisible();
  await option.focus();
  await page.keyboard.press("Escape");
  await expect(listbox).toBeHidden();
  await expect(modelButton).toBeFocused();
});

test("schedule view tabs are native keyboard controls", async () => {
  await page.goto("/schedules", { waitUntil: "domcontentloaded" });

  const historyTab = page.getByRole("tab", { name: "history" });
  await expect(historyTab).toBeVisible({ timeout: 10000 });
  await historyTab.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("execution history will appear here")).toBeVisible();

  // The enable toggle is a labelled switch when a schedule exists. A fresh hive
  // seeds one; an emptied store renders none, which is not a failure here.
  const scheduleSwitch: Locator = page.getByRole("switch").first();
  if (await scheduleSwitch.count()) {
    const before = await scheduleSwitch.getAttribute("aria-checked");
    await scheduleSwitch.focus();
    await expect(scheduleSwitch).toBeFocused();
    await page.keyboard.press("Space");
    await expect(scheduleSwitch).not.toHaveAttribute("aria-checked", before ?? "");
  }
});

test("primary page controls are reachable in the real tab order", async () => {
  const journeys: { path: string; expected: RegExp[] }[] = [
    { path: "/agents", expected: [/\+ Create/, /Open .* details/] },
    { path: "/mcp", expected: [/Test connection/, /\+ add server/, /:servers/] },
    // The per-provider "save" button is disabled until a value is entered, so
    // it is correctly absent from the tab order; the reveal toggle and the
    // token input are the always-reachable controls.
    { path: "/credentials", expected: [/Show Google Gemini API key/, /Google Gemini API key/] },
    { path: "/rsi", expected: [/Refresh/, /Repo path/] },
    { path: "/cli/canvas", expected: [/Poster/, /Describe the artifact/] },
  ];

  for (const journey of journeys) {
    await page.goto(journey.path, { waitUntil: "domcontentloaded" });
    const order = await tabOrder(page);
    for (const pattern of journey.expected) {
      expect(
        isReachable(order, pattern),
        `${pattern} is not reachable by Tab on ${journey.path}`,
      ).toBe(true);
    }
  }
});

test("setup step navigation and hardware choices are buttons", async () => {
  await page.goto("/setup", { waitUntil: "domcontentloaded" });

  // Step 0 requires a name before "next" is enabled — focusing a disabled
  // button is a no-op, so fill it first.
  await page.getByLabel("Conductor name").fill("Keyboard Test Hive");
  const next = page.getByRole("button", { name: /next/ });
  await next.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Pick your hardware tier")).toBeVisible({ timeout: 10000 });

  const hardwareChoices = page
    .getByRole("button")
    .filter({ hasText: /Beast|Laptop|Desktop|Server/ });
  if (await hardwareChoices.count()) {
    await hardwareChoices.first().focus();
    await page.keyboard.press("Space");
    await expect(hardwareChoices.first()).toHaveAttribute("aria-pressed", "true");
  }
});
