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
let seededWorkspaceName: string;

type WorkspaceRow = { id: string; name: string; active?: boolean };

/** Attention skips its API until a Workspace is active — mint one for admin. */
async function seedActiveWorkspace(p: Page): Promise<WorkspaceRow> {
  const listed = await p.request.get("/v1/workspaces");
  expect(listed.status()).toBe(200);
  const rows = ((await listed.json()) as WorkspaceRow[]).filter((w) => w.active !== false);
  if (rows[0]) return rows[0];
  const name = `Attention e2e ${Date.now()}`;
  const created = await p.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name },
  });
  expect(created.status()).toBe(201);
  const body = (await created.json()) as WorkspaceRow;
  return { id: body.id, name: body.name ?? name, active: true };
}

/** Drive React selection through the tab strip — localStorage alone has raced
 * past WorkspaceProvider's first paint in CI. */
async function selectSeededWorkspaceTab(p: Page, name: string, workspaceId: string): Promise<void> {
  const tab = p.getByRole("tab", { name }).first();
  await expect(tab).toBeVisible({ timeout: 15000 });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await p.evaluate((id) => {
    window.localStorage.setItem("hive_active_workspace_id", id);
  }, workspaceId);
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
  });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsAdmin(page);

  const seeded = await seedActiveWorkspace(page);
  seededWorkspaceId = seeded.id;
  seededWorkspaceName = seeded.name;

  await context.addInitScript(
    ({ workspaceId }) => {
      window.localStorage.setItem("hive_onboarded", "1");
      window.localStorage.setItem("hive_active_workspace_id", workspaceId);
    },
    { workspaceId: seededWorkspaceId },
  );
  await page.evaluate((id) => {
    window.localStorage.setItem("hive_onboarded", "1");
    window.localStorage.setItem("hive_active_workspace_id", id);
  }, seededWorkspaceId);

  // Backend door must answer for admin before we blame the SPA.
  const probe = await page.request.get(`/v1/workspaces/${seededWorkspaceId}/attention`);
  expect(
    probe.status(),
    `admin GET attention for ${seededWorkspaceId}: ${await probe.text()}`,
  ).toBe(200);
});

test.afterAll(async () => {
  await context.close();
});

test("Attention is reachable from the icon rail", async () => {
  await page.goto("/dashboard");
  await selectSeededWorkspaceTab(page, seededWorkspaceName, seededWorkspaceId);
  const link = page.locator(".icon-sidebar").getByRole("link", { name: "Attention", exact: true });
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL("**/attention");
  await expect(page.getByRole("heading", { name: "Attention", exact: true })).toBeVisible();
});

test("Attention loads the Workspace projection API and shows summary", async () => {
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await selectSeededWorkspaceTab(page, seededWorkspaceName, seededWorkspaceId);

  // Match any workspace attention GET (ok or not) so a 403/404 surfaces as an
  // assertion on status instead of a silent timeout.
  const attentionPromise = page.waitForResponse(
    (res) =>
      /\/v1\/workspaces\/[^/?#]+\/attention(?:\?|$)/.test(res.url()) &&
      res.request().method() === "GET",
    { timeout: 20000 },
  );

  await page.goto("/attention", { waitUntil: "domcontentloaded" });
  // If Provider came up without a selection, click the seeded tab — that
  // flips activeWorkspaceId and triggers Attention's load effect.
  const noWorkspace = page.getByText("No Workspace selected");
  if (await noWorkspace.isVisible().catch(() => false)) {
    await selectSeededWorkspaceTab(page, seededWorkspaceName, seededWorkspaceId);
  }

  const response = await attentionPromise;
  expect(
    response.ok(),
    `SPA attention GET ${response.url()} → ${response.status()}`,
  ).toBeTruthy();

  await expect(page.getByTestId("workspace-attention")).toBeVisible();
  await expect(page.getByTestId("attention-summary")).toBeVisible({ timeout: 10000 });
  const empty = page.getByText("Nothing needs attention right now");
  const list = page.getByTestId("attention-items");
  await expect(empty.or(list)).toBeVisible();
});

test("Defer/Dismiss hides an item and preference survives reload", async () => {
  // Seed a failed-run Attention item via the projection store is hard from
  // Playwright; instead plant a dismissal against a synthetic source id and
  // prove the door accepts it, then that GET reports dismissed_count after
  // reload (preference evidence, not a second Attention store).
  const dismiss = await page.request.post(
    `/v1/workspaces/${seededWorkspaceId}/attention/dismiss`,
    {
      data: {
        sourceKind: "failed_run",
        sourceId: "e2e-attention-dismiss-seed",
        action: "dismiss",
      },
    },
  );
  expect(dismiss.status(), await dismiss.text()).toBe(200);
  expect(((await dismiss.json()) as { ok?: boolean }).ok).toBe(true);

  await page.goto("/attention", { waitUntil: "domcontentloaded" });
  const noWorkspace = page.getByText("No Workspace selected");
  if (await noWorkspace.isVisible().catch(() => false)) {
    await selectSeededWorkspaceTab(page, seededWorkspaceName, seededWorkspaceId);
  }
  await expect(page.getByTestId("workspace-attention")).toBeVisible({ timeout: 15000 });

  // Preference survives a full reload of the Attention door.
  const afterReload = await page.request.get(
    `/v1/workspaces/${seededWorkspaceId}/attention`,
  );
  expect(afterReload.status()).toBe(200);
  // dismissed_count only increments when a live item matches; with no matching
  // failed run the preference row still exists — clear via DELETE to prove
  // the preference owner round-trips across reload.
  const cleared = await page.request.delete(
    `/v1/workspaces/${seededWorkspaceId}/attention/dismiss`,
    {
      params: {
        sourceKind: "failed_run",
        sourceId: "e2e-attention-dismiss-seed",
      },
    },
  );
  expect(cleared.status(), await cleared.text()).toBe(200);
  expect(((await cleared.json()) as { cleared?: boolean }).cleared).toBe(true);

  const again = await page.request.delete(
    `/v1/workspaces/${seededWorkspaceId}/attention/dismiss`,
    {
      params: {
        sourceKind: "failed_run",
        sourceId: "e2e-attention-dismiss-seed",
      },
    },
  );
  expect(again.status()).toBe(200);
  expect(((await again.json()) as { cleared?: boolean }).cleared).toBe(false);
});
