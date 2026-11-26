/**
 * The Schedules journey completes from the keyboard alone (#370).
 *
 * MCP page keyboard journeys lived on MCP.tsx and left with that module
 * (#2273). /mcp now redirects to Capabilities; this file keeps the Schedules
 * contract and asserts the MCP URL does not revive the deleted page.
 */

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

const schedule = {
  id: "sched-kbd-1",
  name: "Nightly digest",
  description: "summarise the day",
  cron_expression: "0 0 * * *",
  mission_template_id: null,
  enabled: true,
  last_run: null,
  next_run: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

const scheduleWrites: unknown[] = [];

test.beforeAll(async ({ browser }) => {
  // An explicit context, not `browser.newPage()`: AxeBuilder refuses a page
  // whose context it did not see created.
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);

  let current = { ...schedule };
  await page.route("**/v1/schedules", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([current]) });
  });
  await page.route("**/v1/schedules/*", async (route) => {
    if (route.request().method() !== "PUT") return route.fallback();
    const body = route.request().postDataJSON() as Record<string, unknown>;
    scheduleWrites.push(body);
    current = { ...current, ...body };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
  });
});

test.afterAll(async () => {
  await context?.close();
});

async function isFocused(target: Locator) {
  return target.evaluate((element) => document.activeElement === element);
}

async function tabTo(target: Locator, limit = 80) {
  for (let step = 0; step < limit && !(await isFocused(target)); step += 1) {
    await page.keyboard.press("Tab");
  }
  await expect(target).toBeFocused();
}

async function expectVisibleFocus(target: Locator) {
  await expect(target).toBeFocused();
  const outline = await target.evaluate((element) => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: parseFloat(style.outlineWidth), color: style.outlineColor };
  });
  expect(outline.style).not.toBe("none");
  expect(outline.width).toBeGreaterThanOrEqual(2);
  expect(outline.color).not.toBe("rgba(0, 0, 0, 0)");
}

async function expectNoAxeViolations() {
  // `color-contrast` excluded and only that, as in #1460: the findings are
  // palette decisions belonging to #376's contrast floors.
  const results = await new AxeBuilder({ page })
    .include("main")
    .disableRules(["color-contrast"])
    .analyze();
  expect(results.violations).toEqual([]);
}

test("a schedule can be viewed, disabled and given a preset from the keyboard", async () => {
  await page.goto("/schedules", { waitUntil: "domcontentloaded" });

  const tabs = page.getByRole("tablist", { name: "Schedule views" });
  const schedulesTab = tabs.getByRole("tab", { name: "Schedules" });
  const historyTab = tabs.getByRole("tab", { name: "History" });
  await expect(page.getByText(schedule.name)).toBeVisible();

  // Roving tabindex: only the selected tab is a tab stop.
  await expect(historyTab).toHaveAttribute("tabindex", "-1");
  await tabTo(schedulesTab);
  await expect(schedulesTab).toHaveAttribute("aria-selected", "true");

  await page.keyboard.press("ArrowRight");
  await expect(historyTab).toBeFocused();
  await expect(historyTab).toHaveAttribute("aria-selected", "true");
  await expect(schedulesTab).toHaveAttribute("aria-selected", "false");
  const historyPanel = page.getByRole("tabpanel", { name: "History" });
  await expect(historyPanel).toContainText("execution history will appear here");
  // Text-only panels need a tab stop so keyboard users can enter their content.
  await page.keyboard.press("Tab");
  await expect(historyPanel).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(historyTab).toBeFocused();
  await page.keyboard.press("Control+ArrowLeft");
  await expect(historyTab).toBeFocused();
  await expect(historyTab).toHaveAttribute("aria-selected", "true");

  await page.keyboard.press("Home");
  await expect(schedulesTab).toBeFocused();
  await expect(schedulesTab).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("End");
  await expect(historyTab).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight");
  await expect(schedulesTab).toBeFocused();
  await expect(schedulesTab).toHaveAttribute("aria-selected", "true");

  const enable = page.getByRole("switch", { name: `Enable schedule ${schedule.name}` });
  await tabTo(enable, 12);
  await expect(enable).toHaveAttribute("aria-checked", "true");
  await expectVisibleFocus(enable);
  const [write] = await Promise.all([
    page.waitForRequest((r) => r.url().includes(`/v1/schedules/${schedule.id}`) && r.method() === "PUT"),
    page.keyboard.press("Space"),
  ]);
  expect(write.postDataJSON()).toEqual({ enabled: false });
  await expect(enable).toHaveAttribute("aria-checked", "false");
  expect(scheduleWrites).toEqual([{ enabled: false }]);
  await expect(page.locator(".card", { hasText: schedule.name }).getByText("off", { exact: true })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(enable).toHaveAttribute("aria-checked", "true");
  expect(scheduleWrites).toEqual([{ enabled: false }, { enabled: true }]);
  await expect(enable).toBeFocused();

  const create = page.getByRole("button", { name: "+ new" });
  for (let step = 0; step < 12 && !(await isFocused(create)); step += 1) {
    await page.keyboard.press("Shift+Tab");
  }
  await expect(create).toBeFocused();
  await page.keyboard.press("Enter");

  const presets = page.getByRole("group", { name: "Cron presets" });
  const hourly = presets.getByRole("button", { name: "Every hour" });
  const sixHourly = presets.getByRole("button", { name: "Every 6 hours" });
  await expect(hourly).toHaveAttribute("aria-pressed", "true");
  await tabTo(sixHourly, 6);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("textbox", { name: "Cron expression" })).toHaveValue("0 */6 * * *");
  await expect(sixHourly).toHaveAttribute("aria-pressed", "true");
  await expectVisibleFocus(sixHourly);
  await expect(hourly).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Shift+Tab");
  await expect(hourly).toBeFocused();
  await page.keyboard.press("Space");
  await expect(hourly).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("textbox", { name: "Cron expression" })).toHaveValue("0 * * * *");

  // An empty name keeps Create disabled and out of the tab sequence.
  const submit = page.getByRole("button", { name: "create", exact: true });
  await expect(submit).toBeDisabled();
  const template = page.getByPlaceholder("mission template ID (optional)");
  await tabTo(template, 10);
  await page.keyboard.press("Tab");
  const cancel = page.getByRole("button", { name: "cancel", exact: true });
  await expect(cancel).toBeFocused();

  // Returning to a still-open form must not let its mount autofocus steal
  // focus from the tab and break subsequent arrow-key navigation.
  await tabTo(schedulesTab);
  await page.keyboard.press("ArrowRight");
  await expect(historyTab).toBeFocused();
  await expect(page.getByPlaceholder("schedule name", { exact: true })).toBeHidden();
  await page.keyboard.press("ArrowLeft");
  await expect(schedulesTab).toBeFocused();
  await page.keyboard.press("End");
  await expect(historyTab).toBeFocused();
  await page.keyboard.press("Home");
  await expect(schedulesTab).toBeFocused();
  await expectVisibleFocus(schedulesTab);
  await expect(page.getByPlaceholder("schedule name", { exact: true })).toBeVisible();
  await expectNoAxeViolations();
  await tabTo(cancel, 15);
  await page.keyboard.press("Enter");
  await expect(page.getByPlaceholder("schedule name", { exact: true })).toBeHidden();
});

test("/mcp redirects to Capabilities — MCP page module is not revived (#2273)", async () => {
  await page.goto("/mcp", { waitUntil: "domcontentloaded" });
  await page.waitForURL("**/capabilities");
  await expect(page.getByRole("heading", { name: "Capabilities", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "MCP", exact: true })).toHaveCount(0);
  await expect(page.getByRole("tablist", { name: "MCP views" })).toHaveCount(0);
});
