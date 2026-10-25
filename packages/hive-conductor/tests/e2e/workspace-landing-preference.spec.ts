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

test("recent-return restores the prior surface inside the aggressiveness window", async () => {
  // Default landing is Home; a fresh last-surface for Chat within the
  // generous window must win (#1050 recent-return precedence).
  // Seed via addInitScript so LastSurfaceTracker pagehide on an outgoing
  // /home document cannot overwrite the fixture before `/` mounts.
  await page.request.put("/v1/profile", {
    data: {
      preferences: {
        workspace_default_landing: "/home",
        workspace_restore_aggressiveness: "generous",
      },
    },
  });
  const now = Date.now();
  await page.addInitScript(
    ([leftAt, started]) => {
      window.localStorage.setItem(
        "hive_last_surface",
        JSON.stringify({
          path: "/chat",
          leftAtMs: leftAt,
          sessionStartedAtMs: started,
        }),
      );
    },
    [now - 60_000, now - 10 * 60_000],
  );
  await page.goto("/");
  await page.waitForURL("**/chat");
  await expect(page.getByLabel("Chat messages")).toBeVisible({ timeout: 15000 });
});

test("restore aggressiveness off always uses the default landing", async () => {
  await page.request.put("/v1/profile", {
    data: {
      preferences: {
        workspace_default_landing: "/goals",
        workspace_restore_aggressiveness: "off",
      },
    },
  });
  const now = Date.now();
  await page.addInitScript(
    ([leftAt, started]) => {
      window.localStorage.setItem(
        "hive_last_surface",
        JSON.stringify({
          path: "/chat",
          leftAtMs: leftAt,
          sessionStartedAtMs: started,
        }),
      );
    },
    [now - 30_000, now - 5 * 60_000],
  );
  await page.goto("/");
  await page.waitForURL("**/goals");
  await expect(page.getByRole("heading", { name: "Goals", exact: true })).toBeVisible({
    timeout: 15000,
  });
});

test("learned-landing proposal accept writes the durable default; dismiss suppresses nag", async () => {
  await page.request.put("/v1/profile", {
    data: {
      preferences: {
        workspace_default_landing: "/home",
        workspace_restore_aggressiveness: "off",
      },
    },
  });
  await page.goto("/home");
  // Seed the published streak band (LEARNED_STREAK_MIN = 3) without waiting
  // for real immediate hops — observation is already covered by policy tests.
  await page.evaluate(() => {
    window.localStorage.setItem(
      "hive_landing_nav_pattern",
      JSON.stringify({ path: "/goals", streak: 3, lastAtMs: Date.now() }),
    );
    window.localStorage.removeItem("hive_landing_suggestion_suppressed");
  });
  await page.goto("/home");
  const banner = page.getByTestId("landing-suggestion-banner");
  await expect(banner).toBeVisible({ timeout: 10000 });

  await page.getByTestId("landing-suggestion-dismiss").click();
  await expect(banner).toHaveCount(0);

  // Dismiss suppresses — seeding the streak again must not re-nag.
  await page.evaluate(() => {
    window.localStorage.setItem(
      "hive_landing_nav_pattern",
      JSON.stringify({ path: "/goals", streak: 5, lastAtMs: Date.now() }),
    );
  });
  await page.goto("/chat");
  await page.goto("/home");
  await expect(page.getByTestId("landing-suggestion-banner")).toHaveCount(0);

  // Clear suppress and accept → durable preference.
  await page.evaluate(() => {
    window.localStorage.removeItem("hive_landing_suggestion_suppressed");
    window.localStorage.setItem(
      "hive_landing_nav_pattern",
      JSON.stringify({ path: "/goals", streak: 3, lastAtMs: Date.now() }),
    );
  });
  await page.goto("/home");
  await expect(page.getByTestId("landing-suggestion-banner")).toBeVisible({ timeout: 10000 });
  await page.getByTestId("landing-suggestion-accept").click();
  await expect(page.getByTestId("landing-suggestion-banner")).toHaveCount(0);

  const profile = await page.request.get("/v1/profile");
  expect(profile.status()).toBe(200);
  const body = (await profile.json()) as { preferences?: { workspace_default_landing?: string } };
  expect(body.preferences?.workspace_default_landing).toBe("/goals");

  // Explicit default outranks learning — no banner even with a hot streak.
  await page.evaluate(() => {
    window.localStorage.setItem(
      "hive_landing_nav_pattern",
      JSON.stringify({ path: "/chat", streak: 9, lastAtMs: Date.now() }),
    );
  });
  await page.goto("/home");
  await expect(page.getByTestId("landing-suggestion-banner")).toHaveCount(0);
});
