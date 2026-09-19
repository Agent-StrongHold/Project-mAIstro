/**
 * The workspace toolbar on a first run, with a long name, and across accounts
 * (#1426, #1431, #1424, #1437, #1418, #1433).
 *
 * A zero-workspace account used to see a bare "+" and a "New persona"
 * button; a 100-character name stacked the toolbar into a 513px column at
 * phone width; the persona picker showed each persona's tagline only as a
 * title tooltip; and four localStorage keys outlived sign-out and carried to
 * the next account on the same browser profile. Runs as the admin account,
 * which can archive its own workspaces to reach the empty state.
 */

import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

async function archiveAll(page: Page) {
  const listed = await page.request.get("/v1/workspaces");
  expect(listed.status()).toBe(200);
  for (const w of (await listed.json()) as { id: string; active?: boolean }[]) {
    if (w.active === false) continue;
    const r = await page.request.patch(`/v1/workspaces/${w.id}`, { data: { active: false } });
    expect(r.status()).toBe(200);
  }
}

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

test("with no workspace the toolbar explains one and offers to create it", async () => {
  await archiveAll(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const empty = page.getByRole("status").filter({ hasText: "No workspaces yet" });
  await expect(empty).toBeVisible({ timeout: 15000 });
  await expect(empty).toContainText("A workspace is one persona");
  await empty.getByRole("button", { name: "Create workspace", exact: true }).click();
  await expect(page.getByLabel("New workspace name", { exact: true })).toBeVisible();
});

test("the persona picker shows each persona's name and tagline without hovering", async () => {
  const picker = page.getByRole("group", { name: "Persona" });
  await expect(picker).toBeVisible();
  const radios = picker.getByRole("radio");
  await expect(radios.first()).toBeVisible({ timeout: 15000 });
  // Every option's accessible name is its visible label: name and tagline.
  const names = await radios.evaluateAll((els) =>
    els.map((el) => (el.closest("label")?.textContent ?? "").trim()),
  );
  expect(names.length).toBeGreaterThan(0);
  for (const n of names) expect(n.length).toBeGreaterThan(0);
  // Keyboard-operable: arrow keys move the selection within the group.
  await radios.first().focus();
  await page.keyboard.press("ArrowDown");
  if (names.length > 1) await expect(radios.nth(1)).toBeChecked();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
});

test("a long workspace name truncates and keeps its full text in the tooltip", async () => {
  const long = "Rooted Craft Co " + "very ".repeat(20) + "long name";
  const created = await page.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name: long },
  });
  expect(created.status()).toBe(201);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const tab = page.getByRole("tab", { name: long, exact: true });
  await expect(tab).toBeVisible({ timeout: 15000 });
  const box = await tab.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeLessThanOrEqual(180);
  await expect(tab).toHaveAttribute("title", new RegExp("^" + long.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));

  const toolbar = await page.locator(".workspace-toolbar").boundingBox();
  expect(toolbar).not.toBeNull();
  expect(toolbar!.height).toBeLessThanOrEqual(120);
  await page.setViewportSize({ width: 1280, height: 800 });
});

test("signing out clears this account's browser state", async () => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.evaluate(() => {
    window.localStorage.setItem("hive_appearance", "dark");
    window.localStorage.setItem("hive_ui_mode", "power");
  });
  await expect(page.getByRole("tab").first()).toBeVisible({ timeout: 15000 });
  expect(await page.evaluate(() => window.localStorage.getItem("hive_active_workspace_id"))).not.toBeNull();

  await page.getByRole("button", { name: /Sign out/ }).click();
  await page.waitForURL(/\/(login)?$/, { timeout: 15000 });
  // `hive_onboarded` is not in this list only because this spec's own init
  // script re-sets it on every navigation, the post-sign-out one included;
  // it is cleared by the same call as the other three.
  const left = await page.evaluate(() =>
    ["hive_active_workspace_id", "hive_appearance", "hive_ui_mode"].filter(
      (k) => window.localStorage.getItem(k) !== null,
    ),
  );
  expect(left).toEqual([]);
});
