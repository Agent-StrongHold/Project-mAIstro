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

/** Attention skips its API until a Workspace is active — mint one for admin. */
async function ensureActiveWorkspace(): Promise<string> {
  const listed = await page.request.get("/v1/workspaces");
  expect(listed.status()).toBe(200);
  const rows = ((await listed.json()) as { id: string; active?: boolean }[]).filter(
    (w) => w.active !== false,
  );
  let workspaceId = rows[0]?.id;
  if (!workspaceId) {
    const created = await page.request.post("/v1/workspaces", {
      data: { persona_template_id: "pm_fleet", name: `Attention e2e ${Date.now()}` },
    });
    expect(created.status()).toBe(201);
    workspaceId = (await created.json()).id as string;
  }
  await page.evaluate((id) => {
    window.localStorage.setItem("hive_active_workspace_id", id);
  }, workspaceId);
  return workspaceId;
}

test("Attention is reachable from the icon rail", async () => {
  await page.goto("/dashboard");
  const link = page.locator(".icon-sidebar").getByRole("link", { name: "Attention", exact: true });
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL("**/attention");
  await expect(page.getByRole("heading", { name: "Attention", exact: true })).toBeVisible();
});

test("Attention loads the Workspace projection API and shows summary", async () => {
  const workspaceId = await ensureActiveWorkspace();
  const attention = page.waitForResponse(
    (res) =>
      res.url().includes(`/v1/workspaces/${workspaceId}/attention`) &&
      res.request().method() === "GET" &&
      res.ok(),
  );
  await page.goto("/attention");
  await attention;
  await expect(page.getByTestId("workspace-attention")).toBeVisible();
  await expect(page.getByTestId("attention-summary")).toBeVisible();
  // Empty or populated — never a fabricated importance ladder.
  const empty = page.getByText("Nothing needs attention right now");
  const list = page.getByTestId("attention-items");
  await expect(empty.or(list)).toBeVisible();
});
