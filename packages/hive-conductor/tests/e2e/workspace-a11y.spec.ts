/**
 * Status messages announce, and wizard fields are named by their visible
 * labels (#1405, #1416).
 *
 * #1405 (WCAG 4.1.3): a toast, and the error a workspace panel shows when a
 * save or invite is refused, are status messages. They used to be plain
 * divs, so assistive technology said nothing at exactly the moments a person
 * most needs feedback. The toast container is now a polite live region and
 * the four workspace-panel error regions are alerts. These tests ask the
 * accessibility tree, not the DOM: a message must be findable *by its role*
 * for a screen reader to announce it.
 *
 * #1416 (WCAG 2.5.3): two persona-wizard fields carried an `aria-label`
 * shorter than the label shown on screen, so a voice-control user saying the
 * words they could see matched nothing. The wrapping <label> now names each
 * field with its full visible text.
 */

import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
  // The share and tools panels render only for an active workspace.
  const created = await page.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name: "Announce check" },
  });
  expect(created.status()).toBe(201);
});

test.afterAll(async () => {
  await context.close();
});

test("a toast is announced as a status message", async () => {
  // Refuse the roster request so the Agents page raises its error toast;
  // the toast's text is the page's, the region's role is what is under test.
  await page.route("**/v1/agents*", (route) => route.abort());
  await page.goto("/agents", { waitUntil: "domcontentloaded" });
  const toast = page.getByRole("status").filter({ hasText: "Failed to load agents" });
  await expect(toast).toBeVisible({ timeout: 15000 });
  await page.unroute("**/v1/agents*");
});

test("a refused workspace invite is announced as an alert", async () => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /^Share \(/ }).click();
  await page.getByLabel("Invite user id", { exact: true }).fill("nobody-of-that-name");
  // Adding a member is a protected write; the daily-user account is refused,
  // and that refusal is the message the audit found silent.
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible({ timeout: 15000 });
  await expect(alert).not.toHaveText("");
});

test("persona wizard fields are named by their visible labels", async () => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "New persona", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create a new persona" });
  await expect(dialog).toBeVisible();

  const personaId = dialog.getByLabel("Persona id (lowercase, underscores)", { exact: true });
  await expect(personaId).toBeVisible();
  await personaId.fill("announce_check");
  await dialog.getByLabel("Display name", { exact: true }).fill("Announce check");

  // Basics -> Voice -> Scope, where the second renamed field lives.
  await dialog.getByRole("button", { name: "Next", exact: true }).click();
  await dialog.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    dialog.getByLabel("Workspace nav sections (comma-separated)", { exact: true }),
  ).toBeVisible();
});
