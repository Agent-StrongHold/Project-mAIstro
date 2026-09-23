/**
 * Workspace-scoped pages wait for the workspace to resolve (#1427).
 *
 * On a first-ever session `WorkspaceContext` has no stored active id until
 * GET /v1/workspaces returns, and the pages that scope their requests to the
 * active workspace used to fire before that: `/v1/work-items?workspace_id=`
 * with nothing after the `=`, a refusal, an error flash, and then a second,
 * correct request. The acceptance check is the audit's: no workspace-scoped
 * request is ever issued with an empty id. So this records every request the
 * pages make and fails on the first one that names a workspace and leaves it
 * blank -- on a fresh account with no workspace at all, and again once one
 * exists, when every scoped request must carry its id.
 */

import { test, expect, type BrowserContext, type Page, type Request } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
const requests: string[] = [];

const SCOPED_PAGES = ["/work-items", "/agents", "/missions"];

/** Every recorded request that names a workspace, split into blank and named. */
function scoped(): { blank: string[]; named: string[] } {
  const blank: string[] = [];
  const named: string[] = [];
  for (const url of requests) {
    const value = new URL(url).searchParams.get("workspace_id");
    if (value === null) continue;
    (value === "" ? blank : named).push(url);
  }
  return { blank, named };
}

async function visitScopedPages() {
  for (const path of SCOPED_PAGES) {
    // `domcontentloaded`: /agents keeps a long-lived connection open, so the
    // load event is not a signal of anything.
    await page.goto(path, { waitUntil: "domcontentloaded" });
    // The provider resolves the workspace list after mount; give the page the
    // one round trip it needs so a request fired late is still seen.
    await page.waitForResponse((r) => r.url().includes("/v1/workspaces"), { timeout: 15000 });
    await page.waitForLoadState("networkidle");
  }
}

test.beforeAll(async ({ browser }) => {
  // A new context is a first-ever session: nothing in localStorage, so no
  // stored active workspace id -- the exact state the audit reproduced.
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
  page.on("request", (r: Request) => {
    if (r.url().includes("/v1/")) requests.push(r.url());
  });
});

test.afterAll(async () => {
  await context.close();
});

test("with no workspace, scoped pages issue no request with an empty id", async () => {
  // In CI the account holds no workspace here: the hive container is fresh
  // and the PM account was created moments ago by the setup wizard. Locally a
  // previous run may have left one behind, and the daily-user account cannot
  // archive or delete it (both are `workspaces.write`, which it is not
  // granted), so the empty-state assertion below is made only when the
  // account really is empty. The blank-request assertion holds either way.
  const listed = await page.request.get("/v1/workspaces");
  expect(listed.status()).toBe(200);
  const live = ((await listed.json()) as { active?: boolean }[]).filter((w) => w.active !== false);

  requests.length = 0;
  await visitScopedPages();

  const { blank } = scoped();
  expect(blank, "requests that named a workspace and left it blank").toEqual([]);

  // And the page says why there is nothing to show, rather than an error.
  if (live.length === 0) {
    await page.goto("/work-items", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("status")).toContainText("No workspace selected");
  }
});

test("once a workspace exists, every scoped request carries its id", async () => {
  const created = await page.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name: "Scope check" },
  });
  expect(created.status()).toBe(201);

  // The provider picks the first live workspace, which on a fresh account is
  // the one just created and locally may be an older one; either way the id
  // sent must be one of the account's own.
  const listed = await page.request.get("/v1/workspaces");
  const ids = ((await listed.json()) as { id: string; active?: boolean }[])
    .filter((w) => w.active !== false)
    .map((w) => w.id);
  expect(ids.length).toBeGreaterThan(0);

  requests.length = 0;
  await visitScopedPages();

  const { blank, named } = scoped();
  expect(blank).toEqual([]);
  // The work-items list is the request the audit caught blank; it is now the
  // one that must carry a real id.
  const workItems = named.filter((u) => u.includes("/v1/work-items?"));
  expect(workItems.length).toBeGreaterThan(0);
  for (const u of workItems) {
    expect(ids).toContain(new URL(u).searchParams.get("workspace_id"));
  }
});
