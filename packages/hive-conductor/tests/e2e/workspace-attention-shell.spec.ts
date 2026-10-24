/**
 * Workspace Attention shell (#1049 first UI slice).
 *
 * Backend GET projection already ships; this proves the SPA surface: nav
 * reaches /attention, the page loads the Workspace Attention API, and empty
 * or populated states are honest (summary from backend, not client ranking).
 */

import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
let seededWorkspaceId: string;

/** Attention skips its API until a Workspace is active — mint one for admin. */
async function seedActiveWorkspace(p: Page): Promise<string> {
  const listed = await p.request.get("/v1/workspaces");
  expect(listed.status()).toBe(200);
  const rows = ((await listed.json()) as { id: string; active?: boolean }[]).filter(
    (w) => w.active !== false,
  );
  let workspaceId = rows[0]?.id;
  if (!workspaceId) {
    const created = await p.request.post("/v1/workspaces", {
      data: { persona_template_id: "pm_fleet", name: `Attention e2e ${Date.now()}` },
    });
    expect(created.status()).toBe(201);
    workspaceId = (await created.json()).id as string;
  }
  return workspaceId;
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
  });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsAdmin(page);

  seededWorkspaceId = await seedActiveWorkspace(page);
  // Init script so every navigation (including same-URL remounts) sees an
  // active Workspace before WorkspaceProvider's first paint — setting
  // localStorage only after the first /attention visit left the second test
  // waiting forever for an API call that never fired.
  await context.addInitScript(
    ({ onboarded, workspaceId }) => {
      window.localStorage.setItem("hive_onboarded", "1");
      window.localStorage.setItem("hive_active_workspace_id", workspaceId);
    },
    { onboarded: "1", workspaceId: seededWorkspaceId },
  );
  await page.evaluate((id) => {
    window.localStorage.setItem("hive_onboarded", "1");
    window.localStorage.setItem("hive_active_workspace_id", id);
  }, seededWorkspaceId);
});

test.afterAll(async () => {
  await context.close();
});

test("Attention is reachable from the icon rail", async () => {
  await page.goto("/dashboard");
  const link = page.locator(".icon-sidebar").getByRole("link", { name: "Attention", exact: true });
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL("**/attention");
  await expect(page.getByRole("heading", { name: "Attention", exact: true })).toBeVisible();
});

test("Attention loads the Workspace projection API and shows summary", async () => {
  // Leave /attention first: a same-URL goto can soft-reuse the document and
  // miss the waitForResponse registration window.
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

  const attention = page.waitForResponse(
    (res) =>
      res.url().includes(`/v1/workspaces/${seededWorkspaceId}/attention`) &&
      res.request().method() === "GET" &&
      res.ok(),
    { timeout: 15000 },
  );
  await page.goto("/attention", { waitUntil: "domcontentloaded" });
  const response = await attention;
  expect(response.ok()).toBeTruthy();

  await expect(page.getByTestId("workspace-attention")).toBeVisible();
  await expect(page.getByTestId("attention-summary")).toBeVisible({ timeout: 10000 });
  // Empty or populated — never a fabricated importance ladder.
  const empty = page.getByText("Nothing needs attention right now");
  const list = page.getByTestId("attention-items");
  await expect(empty.or(list)).toBeVisible();
});
