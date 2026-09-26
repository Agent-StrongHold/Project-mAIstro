/**
 * Agent builder, intent routing and RSI Stop, keyboard only (#370).
 *
 * Each of these was a click-only generic element: the builder's strategy
 * cards were <div onClick>, the Intent Map's agent cell was a <td onClick>,
 * and the Stop control for a running RSI run was a <span onClick> nested
 * inside the run row's <button> — invalid nested-interactive markup and a
 * safety control no keyboard could reach. Every step below is driven by key
 * presses; nothing is clicked.
 *
 * The roster and every /v1/rsi/* call are intercepted so the journeys do not
 * depend on a model provider or an RSI worker; the Stop POST is intercepted
 * and asserted, not sent.
 */

import AxeBuilder from "@axe-core/playwright";
import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

const AGENTS = [
  { name: "Researcher", model: "gemini-3.5-pro" },
  { name: "Coder", model: "claude-3.5-sonnet" },
].map((a, i) => ({
  id: `agent-${i}`,
  name: a.name,
  description: "",
  model: a.model,
  status: "idle",
  capabilities: [],
  skills: [],
  config: { strategy: "react" },
  tasks_completed: 0,
  avg_response_time_ms: 0,
  current_mission: null,
  last_active: null,
  created_at: "2026-09-26T00:00:00Z",
}));

const RUN_ID = "run-kbd-370";

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  await page.route("**/v1/agents*", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ json: AGENTS });
  });
});

test.afterAll(async () => {
  await context.close();
});

async function scanMain() {
  const results = await new AxeBuilder({ page })
    .include("main")
    .disableRules(["color-contrast"])
    .analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
}

test("the builder's strategy is a radio group operated with arrow keys", async () => {
  await page.goto("/agents", { waitUntil: "domcontentloaded" });
  const builderTab = page.getByRole("button", { name: "Builder", exact: true });
  await expect(builderTab).toBeVisible({ timeout: 15000 });
  await builderTab.focus();
  await page.keyboard.press("Enter");

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Intent Map", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  const describe = page.getByRole("textbox");
  await expect(describe).toBeFocused();
  await page.keyboard.type("Summarise the week's incidents");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /Next/ })).toBeFocused();
  await page.keyboard.press("Enter");

  const group = page.getByRole("radiogroup", { name: "Choose a strategy" });
  await expect(group).toBeVisible();
  const react = group.getByRole("radio", { name: "ReAct" });
  const plan = group.getByRole("radio", { name: "Plan & Execute" });
  await expect(react).toBeChecked();
  await expect(react).toHaveAccessibleDescription(/Reason-Act-Observe/);

  // Focus is not lost when the step it was on unmounts: the next Tab lands
  // on the checked strategy.
  await page.keyboard.press("Tab");
  await expect(react).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(plan).toBeChecked();
  await expect(plan).toBeFocused();
  await expect(react).not.toBeChecked();

  await scanMain();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /Back/ })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /Next/ })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Select model", { exact: true })).toBeVisible();
});

test("intent routing is edited through a disclosure button and Escape returns focus", async () => {
  await page.goto("/agents", { waitUntil: "domcontentloaded" });
  const mapTab = page.getByRole("button", { name: "Intent Map", exact: true });
  await expect(mapTab).toBeVisible({ timeout: 15000 });
  await mapTab.focus();
  await page.keyboard.press("Enter");

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /^Edit routing for tool_dispatch/ })).toBeFocused();
  await page.keyboard.press("Tab");
  const edit = page.getByRole("button", { name: /^Edit routing for research/ });
  await expect(edit).toBeFocused();
  await expect(edit).toHaveAttribute("aria-expanded", "false");

  await page.keyboard.press("Enter");
  await expect(edit).toHaveAttribute("aria-expanded", "true");
  const select = page.getByRole("combobox", { name: "Agent for research" });
  await expect(select).toBeFocused();
  await expect(select).toHaveValue("Researcher");

  await page.keyboard.press("ArrowDown");
  await expect(select).toHaveValue("Coder");

  await scanMain();

  await page.keyboard.press("Escape");
  await expect(select).toHaveCount(0);
  await expect(edit).toBeFocused();
  await expect(edit).toHaveAttribute("aria-expanded", "false");
  await expect(edit).toHaveAccessibleName("Edit routing for research: Coder");
  const row = page.getByRole("row").filter({ has: edit });
  await expect(row).toContainText("claude-3.5-sonnet");
});

test("a running RSI run's Stop is its own button and Enter sends the stop", async () => {
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
  await page.route("**/v1/rsi/status", (r) => r.fulfill({ json: { available: true, active_runs: 1, total_runs: 1 } }));
  await page.route("**/v1/rsi/runs", (r) => r.fulfill({ json: [run] }));
  await page.route("**/v1/rsi/models", (r) => r.fulfill({ json: { models: [] } }));
  await page.route("**/v1/rsi/test-profiles", (r) => r.fulfill({ json: { profiles: [] } }));
  await page.route(`**/v1/rsi/runs/${RUN_ID}/reviews`, (r) => r.fulfill({ json: { kept: [], flagged: [] } }));
  await page.route(`**/v1/rsi/runs/${RUN_ID}/rlphd`, (r) => r.fulfill({ json: {} }));
  const stops: string[] = [];
  await page.route(`**/v1/rsi/runs/${RUN_ID}/stop`, async (r) => {
    stops.push(r.request().method());
    await r.fulfill({ json: { ok: true } });
  });

  await page.goto("/rsi", { waitUntil: "domcontentloaded" });
  const row = page.getByRole("button", { name: `running ${RUN_ID} 1/3 promoted`, exact: true });
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect(row).toHaveAttribute("aria-pressed", "false");

  await row.focus();
  await page.keyboard.press("Enter");
  await expect(row).toHaveAttribute("aria-pressed", "true");

  expect(await page.locator("button button, button a[href], button input, button select, button [role=button]").count()).toBe(0);
  const nested = await new AxeBuilder({ page }).withRules(["nested-interactive"]).analyze();
  expect(nested.violations).toEqual([]);
  await scanMain();

  await page.keyboard.press("Tab");
  const stop = page.getByRole("button", { name: `Stop run ${RUN_ID}`, exact: true });
  await expect(stop).toBeFocused();
  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().endsWith(`/v1/rsi/runs/${RUN_ID}/stop`)),
    page.keyboard.press("Enter"),
  ]);
  expect(request.method()).toBe("POST");
  expect(stops).toEqual(["POST"]);
  // The stop is its own action: it must not also toggle the row.
  await expect(row).toHaveAttribute("aria-pressed", "true");
});
