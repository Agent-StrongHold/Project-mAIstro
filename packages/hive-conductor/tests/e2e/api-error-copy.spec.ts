/**
 * API failures surface as human copy, not raw transport strings (#1436).
 *
 * `lib/api.ts`'s shared `request()` used to throw
 * `new Error(\`${path}: ${detail}\`)`, falling back to the bare status code
 * (\`500\`) when the backend gave no `detail`. Every caller that renders
 * `err.message` -- toasts, inline errors -- showed the internal route and a
 * number a user can't act on. The thrown message is now the backend's
 * `detail` on its own when present (already a human sentence in this API,
 * e.g. a permission-elevation message), or one of a small set of
 * status-family sentences with a recovery hint when it isn't; the raw
 * path/status still travel on the error's `.path`/`.status` for developer
 * diagnostics (and were already logged to the console by `debugApi`), just
 * not in the primary message.
 */

import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  const created = await page.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name: `API error copy ${Date.now()}` },
  });
  expect(created.status()).toBe(201);
  const wsId = (await created.json()).id as string;
  await page.addInitScript((id: string) => {
    window.localStorage.setItem("hive_active_workspace_id", id);
  }, wsId);
});

test.afterAll(async () => {
  await context.close();
});

test("a failed request with no backend detail shows a human sentence, not a bare status or route", async () => {
  await page.route("**/v1/work-items*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    // No `detail` field -- the case that used to fall back to the raw
    // status code as the entire user-facing message.
    await route.fulfill({ status: 500, json: { error: "internal" } });
  });

  await page.goto("/work-items", { waitUntil: "domcontentloaded" });
  const toast = page.getByRole("status").filter({ hasText: /./ });
  await expect(toast).toBeVisible({ timeout: 15000 });
  const text = (await toast.textContent()) ?? "";

  expect(text).not.toContain("/v1/work-items");
  expect(text.trim()).not.toBe("500");
  expect(text).not.toMatch(/^500$/);
  expect(text.toLowerCase()).toContain("try again");

  await page.unroute("**/v1/work-items*");
});
