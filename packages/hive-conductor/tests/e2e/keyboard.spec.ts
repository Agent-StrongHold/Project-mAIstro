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
 *
 * Surface ownership after the Workspace cutover (#2273/#2274/#1049 merged the
 * Agents/MCP/Skills/Topology/Dashboard pages away):
 *
 * - the shell skip link and the chat model-menu focus contract stay here;
 * - the Schedules tabs/switch contract lives in
 *   `schedules-mcp-keyboard.spec.ts`;
 * - the Design Studio editor walks live in `design-studio-keyboard.spec.ts`;
 * - the agent-builder/RSI-Stop contract lives in
 *   `agents-rsi-keyboard.spec.ts`;
 * - journeys that targeted deleted pages walk their successors instead
 *   (/dashboard → /home, /agents + /mcp → /capabilities).
 */

import { test, expect, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { loginAsAdmin, loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
// #373: /rsi sits behind PermissionBoundary("rsi.execute"), so its walk runs
// under the admin account in its own context — the same arrangement
// agents-rsi-keyboard.spec.ts uses. The PM session above stays untouched.
let rsiContext: BrowserContext;
let rsiPage: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
  });
  // The onboarding tour is a full-screen dialog on a fresh install; mark it
  // seen before the app's own scripts run so it cannot cover these pages.
  await context.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  page = await context.newPage();

  // Chat's model list drives the model-menu journey. Serving a deterministic
  // catalog keeps the journey independent of whether the harness ships a
  // gateway that can answer a real discovery call.
  await page.route("**/v1/models", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(["kbd-model-a", "kbd-model-b"]),
    });
  });

  await setupIfNeeded(page);
  await loginAsPM(page);

  // Chat sessions are Workspace-scoped (#1822): without an active workspace the
  // page renders its "Select a Workspace" empty state and the model menu never
  // mounts. Reuse an existing workspace when one exists so repeated runs do not
  // accumulate throwaway rows, and pin it the same way the app persists the
  // last-open tab.
  const listed = await page.request.get("/v1/workspaces");
  expect(listed.status()).toBe(200);
  const rows = (await listed.json()) as { id: string; active?: boolean }[];
  let workspaceId = rows.find((w) => w.active !== false)?.id;
  if (!workspaceId) {
    const created = await page.request.post("/v1/workspaces", {
      data: { persona_template_id: "pm_fleet", name: `Keyboard e2e ${Date.now()}` },
    });
    expect(created.status()).toBe(201);
    workspaceId = ((await created.json()) as { id: string }).id;
  }
  await context.addInitScript(
    ({ workspaceId: id }) => {
      window.localStorage.setItem("hive_active_workspace_id", id);
    },
    { workspaceId },
  );

  rsiContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  await rsiContext.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
  rsiPage = await rsiContext.newPage();
  await setupIfNeeded(rsiPage);
  await loginAsAdmin(rsiPage);
});

test.afterAll(async () => {
  await context.close();
  await rsiContext.close();
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
  // Home is the default landing surface (#2274): the legacy /dashboard page is
  // deleted and its URL redirects here, so the shell contract is asserted on
  // the surface users actually land on.
  await page.goto("/home", { waitUntil: "domcontentloaded" });

  // The skip link is visually hidden with a CSS transform until focused, so
  // Chromium keeps it out of the accessibility tree and getByRole cannot find
  // it. A CSS selector sees it regardless, and focus behaves the same.
  const skip = page.locator("a.skip-link");
  await skip.waitFor({ state: "attached", timeout: 15000 });

  // Chat auto-focuses its message box on mount; Home does not, so dropping
  // focus to <body> and pressing Tab starts a real walk from the top of the
  // document.
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

test("primary page controls are reachable in the real tab order", async () => {
  await page.goto("/capabilities", { waitUntil: "domcontentloaded" });
  // The walks below record the page's tab order; starting one before the
  // page's data has rendered measures the skeleton, not the surface. Each
  // journey therefore waits for its settled state first — polling pages
  // (RSI) never go network-idle, so these are content waits, not network
  // waits.
  await page
    .getByText("No capability slots registered")
    .or(page.locator("section[aria-label^='Capability slot']"))
    .first()
    .waitFor({ state: "visible", timeout: 15000 });
  const capabilitiesOrder = await tabOrder(page);
  // "Re-discover providers" is reachable in both states the page can render:
  // the header button and the empty-state action. The per-slot Enable/Disable
  // buttons are data-dependent — a cold hive registers no slots, so they are
  // asserted only when the data is present, the way the schedules switch is.
  expect(
    isReachable(capabilitiesOrder, /Re-discover providers/),
    "/Re-discover providers/ is not reachable by Tab on /capabilities",
  ).toBe(true);
  // The per-slot Enable/Disable buttons are data-dependent — a cold hive
  // registers no slots, so they are asserted only when the data is present,
  // the way the schedules switch leg of schedules-mcp-keyboard.spec.ts is.
  if ((await page.getByText("No capability slots registered").count()) === 0) {
    expect(
      isReachable(capabilitiesOrder, /^(BUTTON):(Enable|Disable)$/),
      "slot Enable/Disable controls are not reachable by Tab on /capabilities",
    ).toBe(true);
  }

  const journeys: { path: string; expected: RegExp[] }[] = [
    // The per-provider "save" button is disabled until a value is entered, so
    // it is correctly absent from the tab order; the named token fields and
    // the provider-console links are the always-reachable controls.
    { path: "/credentials", expected: [/token/i, /Create or manage token/] },
  ];

  for (const journey of journeys) {
    await page.goto(journey.path, { waitUntil: "domcontentloaded" });
    if (journey.path === "/credentials") {
      await page.getByText("Create or manage token").first().waitFor({ state: "visible", timeout: 15000 });
    }
    const order = await tabOrder(page);
    for (const pattern of journey.expected) {
      expect(
        isReachable(order, pattern),
        `${pattern} is not reachable by Tab on ${journey.path}`,
      ).toBe(true);
    }
  }

  // RSI is an authority-gated surface (#373), so this leg walks the admin
  // session's page.
  await rsiPage.goto("/rsi", { waitUntil: "domcontentloaded" });
  await rsiPage.getByRole("button", { name: "Refresh" }).waitFor({ state: "visible", timeout: 15000 });
  const rsiOrder = await tabOrder(rsiPage);
  for (const pattern of [/Refresh/, /Repo path/]) {
    expect(
      isReachable(rsiOrder, pattern),
      `${pattern} is not reachable by Tab on /rsi`,
    ).toBe(true);
  }
});

test("setup step navigation and hardware choices are buttons", async () => {
  await page.goto("/setup", { waitUntil: "domcontentloaded" });

  // Step 0 requires a name before "next" is enabled — focusing a disabled
  // button is a no-op, so fill it first. The gateway-discovery gate from the
  // session helper applies here too: when no gateway answers, the wizard adds
  // an explicit "availability is UNVERIFIED" acknowledgement checkbox.
  await page.getByLabel("Conductor name").fill("Keyboard Test Hive");
  const unverifiedAck = page.getByTestId("unverified-ack").getByRole("checkbox");
  const ackVisible = await unverifiedAck
    .waitFor({ state: "visible", timeout: 10000 })
    .then(() => true)
    .catch(() => false);
  if (ackVisible) await unverifiedAck.check();
  const next = page.getByRole("button", { name: /next/i });
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
