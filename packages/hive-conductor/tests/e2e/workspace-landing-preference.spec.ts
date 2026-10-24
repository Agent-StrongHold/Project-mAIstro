/**
 * Workspace default landing preference (#1050 first slice).
 *
 * Proves the durable profile preference steers the authenticated index route,
 * and that the Profile control writes the same field.
 */

import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
  });
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsAdmin(page);
});

test.afterAll(async () => {
  await context.close();
});

test("with no preference, the index lands on Workspace Home", async () => {
  await page.request.put("/v1/profile", { data: { preferences: {} } });
  await page.goto("/");
  await page.waitForURL("**/home");
  await expect(page.getByRole("heading", { name: "Home", exact: true })).toBeVisible({
    timeout: 15000,
  });
  await expect(page.getByTestId("workspace-home")).toBeVisible();
});

test("a saved preference steers the index to that surface", async () => {
  await page.request.put("/v1/profile", {
    data: { preferences: { workspace_default_landing: "/chat" } },
  });
  await page.goto("/");
  await page.waitForURL("**/chat");
  // Chat has no h1 — assert the session surface, not a page title.
  await expect(page.getByLabel("Chat messages")).toBeVisible({ timeout: 15000 });
  await expect(page.locator(".chat-header-title")).toHaveText("AI Assistant");
});

test("Profile can set the preference through the same API", async () => {
  await page.goto("/profile");
  const select = page.getByLabel("Workspace default landing");
  await expect(select).toBeVisible();
  await select.selectOption("/goals");
  await expect(page.getByRole("status").filter({ hasText: /Goals/i })).toBeVisible({
    timeout: 10000,
  });
  const profile = await page.request.get("/v1/profile");
  expect(profile.status()).toBe(200);
  const body = (await profile.json()) as { preferences?: { workspace_default_landing?: string } };
  expect(body.preferences?.workspace_default_landing).toBe("/goals");
});

test("Profile can set restore aggressiveness on the same profile", async () => {
  await page.goto("/profile");
  const select = page.getByLabel("Workspace restore aggressiveness");
  await expect(select).toBeVisible();
  await select.selectOption("generous");
  await expect(page.getByRole("status").filter({ hasText: /Generous/i })).toBeVisible({
    timeout: 10000,
  });
  const profile = await page.request.get("/v1/profile");
  expect(profile.status()).toBe(200);
  const body = (await profile.json()) as {
    preferences?: { workspace_restore_aggressiveness?: string };
  };
  expect(body.preferences?.workspace_restore_aggressiveness).toBe("generous");
});

test("API refuses an out-of-allow-list landing path", async () => {
  const res = await page.request.patch("/v1/profile", {
    data: { field: "workspace_default_landing", value: "/dashboard" },
  });
  expect(res.status()).toBe(400);
});
