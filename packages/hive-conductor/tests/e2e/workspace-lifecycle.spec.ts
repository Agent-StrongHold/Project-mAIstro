/**
 * Workspace mutations confirm, ask before they destroy, and cost one request
 * (#1407, #1429, #1428, #1430, #1434).
 *
 * The audit found the workspace toolbar silent and asymmetric: create,
 * archive, delete and tool-binding saves gave no saved signal; Archive was
 * one unconfirmed click beside a two-step Delete; an archived workspace could
 * not be brought back although the backend accepts `PATCH {active: true}`;
 * closing the Tools panel threw away unsaved edits; and every mutation was
 * followed by a refetch of the whole list. These run as the admin account,
 * which holds the `workspaces.write` these actions need without elevation.
 */

import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
const requests: { method: string; url: string }[] = [];
const wsName = `Lifecycle ${Date.now()}`;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
  page.on("request", (r) => {
    if (r.url().includes("/v1/workspaces")) requests.push({ method: r.method(), url: r.url() });
  });
});

test.afterAll(async () => {
  await context.close();
});

test("creating a workspace confirms and selects it", async () => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "New workspace", exact: true }).click();
  await page.getByLabel("New workspace name", { exact: true }).fill(wsName);
  await page.getByRole("group", { name: "Persona" }).locator('input[value="pm_fleet"]').check();
  await page.getByRole("button", { name: "Create", exact: true }).click();

  await expect(page.getByRole("status").filter({ hasText: `Created workspace "${wsName}"` }))
    .toBeVisible({ timeout: 15000 });
  const tab = page.getByRole("tab", { name: wsName, exact: true });
  await expect(tab).toBeVisible();
  await expect(tab).toHaveAttribute("aria-selected", "true");
});

test("the tools panel shows unsaved edits, asks before discarding, and confirms a save", async () => {
  const toggle = page.getByRole("button", { name: /^Tools/ });
  await toggle.click();
  const extra = page.getByLabel(/^Additional tools for /).first();
  await expect(extra).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("button", { name: "Saved", exact: true })).toBeDisabled();

  await extra.fill("e2e_extra_tool");
  await expect(page.getByRole("status").filter({ hasText: "Unsaved changes" })).toBeVisible();
  await expect(toggle).toHaveAccessibleName("Tools (unsaved changes)");

  // A click meant to tuck the panel away does not throw the edit out.
  await toggle.click();
  const ask = page.getByRole("alertdialog", { name: "Discard unsaved changes?" });
  await expect(ask).toBeVisible();
  await ask.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(extra).toHaveValue("e2e_extra_tool");

  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Tool bindings saved" }))
    .toBeVisible({ timeout: 15000 });
  await expect(toggle).toHaveAccessibleName("Tools");
});

test("archive asks first, costs one request, and is reversible from the tab bar", async () => {
  await page.getByRole("button", { name: /^Share \(/ }).click();
  await page.getByRole("button", { name: "Archive workspace", exact: true }).click();
  await expect(page.getByText("Archive? It stays restorable from the tab bar.")).toBeVisible();

  requests.length = 0;
  await page.getByRole("button", { name: "Yes, archive", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: `Archived "${wsName}"` }))
    .toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("tab", { name: wsName, exact: true })).toHaveCount(0);

  // One mutation, one request: the PATCH, and no refetch of the list.
  expect(requests.filter((r) => r.method === "PATCH")).toHaveLength(1);
  expect(requests.filter((r) => r.method === "GET" && /\/v1\/workspaces\/?(\?|$)/.test(r.url)))
    .toHaveLength(0);

  await page.getByRole("button", { name: /^Archived \(\d+\)$/ }).click();
  await page.getByRole("button", { name: `Restore ${wsName}`, exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: `Restored workspace "${wsName}"` }))
    .toBeVisible({ timeout: 15000 });
  const tab = page.getByRole("tab", { name: wsName, exact: true });
  await expect(tab).toBeVisible();
  await expect(tab).toHaveAttribute("aria-selected", "true");
});
