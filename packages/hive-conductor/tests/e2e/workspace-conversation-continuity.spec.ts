/**
 * Workspace chat continuity under delayed stream + switch (#1822).
 *
 * Delayed A1 stream → switch to A2 → late frames must not paint onto A2;
 * the aborted A1 bubble is marked interrupted until reopen reads GET truth.
 */

import { expect, test, type BrowserContext, type Page, type Route } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
let workspaceId: string;

type SessionRow = { id: string; title?: string };

async function seedWorkspace(p: Page): Promise<string> {
  const listed = await p.request.get("/v1/workspaces");
  expect(listed.status()).toBe(200);
  const rows = (await listed.json()) as { id: string; active?: boolean }[];
  const existing = rows.find((w) => w.active !== false);
  if (existing) return existing.id;
  const created = await p.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name: `Continuity e2e ${Date.now()}` },
  });
  expect(created.status()).toBe(201);
  return ((await created.json()) as { id: string }).id;
}

async function createSession(p: Page, ws: string, title: string): Promise<string> {
  const res = await p.request.post("/v1/chat/sessions", {
    data: { title, workspace_id: ws },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return ((await res.json()) as SessionRow).id;
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
  });
  page = await context.newPage();
  await setupIfNeeded(page);
  // Chat sessions refuse the admin account — use the daily PM user (#1822).
  await loginAsPM(page);
  workspaceId = await seedWorkspace(page);
  await context.addInitScript(
    ({ workspaceId: id }) => {
      window.localStorage.setItem("hive_onboarded", "1");
      window.localStorage.setItem("hive_active_workspace_id", id);
    },
    { workspaceId },
  );
});

test.afterAll(async () => {
  await context.close();
});

test("late stream frames after session switch do not land on the new session", async () => {
  const sessionA = await createSession(page, workspaceId, "Continuity A");
  const sessionB = await createSession(page, workspaceId, "Continuity B");

  let releaseLate: (() => void) | null = null;
  const lateGate = new Promise<void>((resolve) => {
    releaseLate = resolve;
  });
  let streamHits = 0;

  await page.route("**/v1/chat/stream", async (route: Route) => {
    streamHits += 1;
    if (streamHits > 1) {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `data: ${JSON.stringify({ type: "done", content: "B-only reply" })}\n\n`,
      });
      return;
    }
    // Hold the first stream open until the test switches sessions, then
    // deliver a late delta+brief+done that must not paint onto session B.
    await lateGate;
    const body =
      `data: ${JSON.stringify({ type: "delta", content: "LATE-A-LEAK" })}\n\n` +
      `data: ${JSON.stringify({
        type: "brief",
        event: "summary",
        summary: {
          known: 1,
          needed: 1,
          ready: false,
          fields: [{ key: "leak", label: "Leak", value: "LATE-BRIEF", source: "assumed" }],
          notes: [],
        },
        question: null,
      })}\n\n` +
      `data: ${JSON.stringify({ type: "done", content: "LATE-A-DONE" })}\n\n`;
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body,
    });
  });

  await page.goto(`/chat?session=${sessionA}`);
  await expect(page.getByLabel("Chat messages")).toBeVisible({ timeout: 15000 });

  const composer = page.locator(".chat-textarea");
  await expect(composer).toBeVisible();
  await composer.fill("start delayed A stream");
  await page.keyboard.press("Enter");

  // Wait until the stream route is hit (optimistic bubble up).
  await expect.poll(() => streamHits).toBe(1);

  // Switch to B while A is still held open.
  await page.goto(`/chat?session=${sessionB}`);
  await expect(page.getByLabel("Chat messages")).toBeVisible({ timeout: 15000 });

  releaseLate?.();

  // Give late frames a moment to arrive; B must stay free of A content.
  await page.waitForTimeout(500);
  await expect(page.getByText("LATE-A-LEAK")).toHaveCount(0);
  await expect(page.getByText("LATE-BRIEF")).toHaveCount(0);
  await expect(page.getByText("LATE-A-DONE")).toHaveCount(0);

  // Reopen A: persisted truth only (no late leak as completed content).
  await page.goto(`/chat?session=${sessionA}`);
  await expect(page.getByLabel("Chat messages")).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("LATE-A-LEAK")).toHaveCount(0);
  await expect(page.getByText("LATE-A-DONE")).toHaveCount(0);

  await page.unroute("**/v1/chat/stream");
});

test("Workspace A→B mid-stream never paints A or posts A's history (#1822 AC-3)", async () => {
  const wsA = workspaceId;
  const createdB = await page.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name: `Isolation B ${Date.now()}` },
  });
  expect(createdB.status()).toBe(201);
  const wsB = ((await createdB.json()) as { id: string }).id;
  const sessionA = await createSession(page, wsA, "Isolation A");
  await createSession(page, wsB, "Isolation B");

  let releaseLate: (() => void) | null = null;
  const lateGate = new Promise<void>((resolve) => {
    releaseLate = resolve;
  });
  const streamBodies: { workspace_id?: string; session_id?: string; messages?: unknown[] }[] =
    [];

  await page.route("**/v1/chat/stream", async (route: Route) => {
    const posted = route.request().postDataJSON() as {
      workspace_id?: string;
      session_id?: string;
      messages?: unknown[];
    };
    streamBodies.push(posted);
    if (posted.workspace_id === wsB) {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `data: ${JSON.stringify({ type: "done", content: "B-only reply" })}\n\n`,
      });
      return;
    }
    await lateGate;
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `data: ${JSON.stringify({ type: "delta", content: "A-ONLY-LEAK" })}\n\n` +
        `data: ${JSON.stringify({ type: "done", content: "A-ONLY-DONE" })}\n\n`,
    });
  });

  await page.goto(`/chat?session=${sessionA}`);
  await expect(page.getByLabel("Chat messages")).toBeVisible({ timeout: 15000 });
  const composer = page.locator(".chat-textarea");
  await composer.fill("A mid-stream marker");
  await page.keyboard.press("Enter");
  await expect.poll(() => streamBodies.length).toBe(1);
  await expect(page.getByText("A mid-stream marker")).toBeVisible();

  // Switch active Workspace via the tab strip (not a same-WS session hop).
  await page.getByRole("tab", { name: new RegExp(`Isolation B`) }).click();
  await expect(page.getByText("A mid-stream marker")).toHaveCount(0);
  await expect(page.getByText("Loading sessions")).toBeVisible({ timeout: 5000 }).catch(() => {
    /* hydrate may already have finished */
  });
  await expect(page.getByText("A-ONLY-LEAK")).toHaveCount(0);

  releaseLate?.();
  await page.waitForTimeout(400);
  await expect(page.getByText("A-ONLY-LEAK")).toHaveCount(0);
  await expect(page.getByText("A-ONLY-DONE")).toHaveCount(0);

  // Any later B stream must not carry A's user text.
  const bPosts = streamBodies.filter((b) => b.workspace_id === wsB);
  for (const body of bPosts) {
    const blob = JSON.stringify(body.messages ?? []);
    expect(blob).not.toContain("A mid-stream marker");
    expect(body.session_id).not.toBe(sessionA);
  }

  await page.unroute("**/v1/chat/stream");
});
