/**
 * Keyboard node manipulation on the DAG Builder saves correctly (#370).
 *
 * `handleNodeKeyDown` gives the canvas node the keyboard equivalents the
 * issue requires: Enter/Space opens the node inspector, ArrowKeys nudge the
 * node and save. Every keypress calls `handleSaveDag`, so holding an arrow
 * key (key-repeat) fires one PUT per repeat — which is the race this spec
 * pins:
 *
 *   - the OLD save path PUT each snapshot independently, so key-repeat
 *     produced overlapping requests whose responses resolved out of order;
 *     a slow response for an early snapshot then `setDag(saved)` rolled the
 *     canvas back to a position the user had already moved past;
 *   - the NEW path serializes (at most one PUT in flight) and coalesces
 *     (callers arriving mid-flight collapse into one trailing save with the
 *     latest snapshot), and a response is only applied when nothing newer
 *     is pending.
 *
 * The assertions are structural, not wall-clock: concurrency is bounded by
 * counting requests that overlap inside the route handler (a stub PUT delay
 * long enough that all presses land inside the first request's window makes
 * the old path deterministically reach in-flight > 1), the trailing save
 * must carry the final position, and a failed save must drop its queued
 * snapshot instead of replaying it stale after the next successful one.
 *
 * Workspaces and the DAG list/detail are stubbed at the HTTP layer the same
 * way `dag-builder-unmount-cleanup.spec.ts` does, so no execution or
 * Workspace state is created on the shared test instance. Like that spec,
 * the page is created once in beforeAll and shared across the serial tests:
 * the HTTP stubs live on THAT page, and a per-test `page` fixture would
 * carry none of them.
 */

import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

const WORKSPACE_ID = "ws-kbd-race";
const DAG_ID = "dag-kbd-race";
const NODE_ID = "node-kbd-race-001";

const dag = {
  id: DAG_ID,
  name: "Keyboard race DAG",
  description: "",
  nodes: [
    // No `_pos` in config: the page's `nodePos()` default (100, 100) is the
    // baseline the arrow-key deltas move away from.
    { id: NODE_ID, role: "worker", name: "alpha", agent_id: null, model: null, strategy: "direct", prompt: null, config: {} },
  ],
  edges: [],
  entry_node: NODE_ID,
  max_cycles: 3,
  run_scout: false,
  status: "active",
  created_at: "2026-11-26T00:00:00Z",
  updated_at: "2026-11-26T00:00:00Z",
};

const workspaces = [
  {
    id: WORKSPACE_ID,
    persona_template_id: "pm_fleet",
    name: "Keyboard race",
    theme_id: "default",
    voice_tone_override: null,
    members: [],
    tool_bindings: [],
    active: true,
  },
];

type SaveBehavior = { firstDelayMs: number; laterDelayMs: number; failFirst: boolean };

let behavior: SaveBehavior = { firstDelayMs: 0, laterDelayMs: 0, failFirst: false };
// Node-side records the route handler fills: one body per PUT REQUEST (at
// send time), completion count at response time, and the max overlap.
let putBodies: Array<Record<string, unknown>> = [];
let putCompletions = 0;
let activePuts = 0;
let maxInFlight = 0;
let firstPutFailed = false;

function resetSaveRecords(next: SaveBehavior) {
  behavior = next;
  putBodies = [];
  putCompletions = 0;
  activePuts = 0;
  maxInFlight = 0;
  firstPutFailed = false;
}

/** The node's rendered canvas position: the rect's x/y attributes. */
async function nodeRectPos(): Promise<{ x: string; y: string }> {
  const rect = page.locator('g[role="button"] rect').first();
  return { x: (await rect.getAttribute("x")) ?? "", y: (await rect.getAttribute("y")) ?? "" };
}

/** Final PUT body position for the node, read from the recorded bodies. */
function lastPutPos(): { x: unknown; y: unknown } {
  const body = putBodies[putBodies.length - 1] as
    | { nodes?: Array<{ id: string; config?: { _pos?: { x: number; y: number } } }> }
    | undefined;
  const node = body?.nodes?.find((n) => n.id === NODE_ID);
  return node?.config?._pos ?? { x: undefined, y: undefined };
}

/**
 * Navigate to the builder and open the fixture DAG through real SPA clicks.
 * Always hops through /dag-runs first: the serial tests share one page, and
 * landing here already on /dags with the DAG selected would skip the remount
 * that refetches server state (the previous test's nudged positions would
 * silently become this test's baseline).
 */
async function openBuilderDag() {
  await page.getByRole("link", { name: "DAG Runs", exact: true }).click();
  await page.getByRole("link", { name: "DAG Builder", exact: true }).click();
  await page.getByRole("button", { name: `Open DAG ${dag.name}` }).click();
  const node = page.getByRole("button", { name: `Open worker node ${NODE_ID}` });
  await expect(node).toBeVisible();
  return node;
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  page = await context.newPage();

  // Registered BEFORE the session helpers run: the app's one and only
  // workspace fetch happens on the post-login mount and must already be
  // intercepted here (same ordering argument as the unmount-cleanup spec).
  await page.route(/\/v1\/workspaces(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(workspaces) });
  });
  await page.route(/\/v1\/dags(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([dag]) });
  });
  await page.route(new RegExp(`/v1/dags/${DAG_ID}$`), async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(dag) });
      return;
    }
    if (route.request().method() !== "PUT") return route.fallback();
    const body = route.request().postDataJSON() as Record<string, unknown>;
    putBodies.push(body);
    activePuts += 1;
    maxInFlight = Math.max(maxInFlight, activePuts);
    const fail = behavior.failFirst && putBodies.length === 1;
    const delay = putBodies.length === 1 ? behavior.firstDelayMs : behavior.laterDelayMs;
    await new Promise((resolve) => setTimeout(resolve, delay));
    activePuts -= 1;
    putCompletions += 1;
    if (fail) {
      firstPutFailed = true;
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "stub save failure" }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route(/\/v1\/agents(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/v1\/settings\/models(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ models: ["test-model"] }) });
  });
  // #1048: post-login `/` lands on Workspace Home; without these stubs the
  // layout/projection 404s surface as console noise the other DAG specs
  // already tolerate, so keep the page silent the same way.
  await page.route(/\/v1\/workspaces\/[^/]+\/home\/layout$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ revision: 1, updatedAt: "2026-11-26T00:00:00Z", regions: [] }),
    });
  });
  await page.route(/\/v1\/workspaces\/[^/]+\/home\/projections$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ workspace_id: WORKSPACE_ID, generated_at: "2026-11-26T00:00:00Z", sections: [], dismissed: {} }),
    });
  });

  await setupIfNeeded(page);
  await loginAsPM(page);
});

test.afterAll(async () => {
  await context.close();
});

test("rapid arrow-key node moves coalesce into serialized, trailing-correct saves", async () => {
  // A 400ms stub PUT: every press of the four-press burst lands inside the
  // first request's window, which is exactly the regime where the unserialised
  // save path had overlapping PUTs and out-of-order responses.
  resetSaveRecords({ firstDelayMs: 400, laterDelayMs: 400, failFirst: false });
  const node = await openBuilderDag();

  // Enter opens the inspector from the keyboard (the click-equivalent path),
  // which also renders the Saving... indicator used as the settle signal.
  await node.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Node Properties", { exact: false }).first()).toBeVisible();
  await expect(node).toBeFocused();

  // Four fast nudges: +10 x each, on top of the (100, 100) default.
  for (let i = 0; i < 4; i += 1) await page.keyboard.press("ArrowRight");
  await expect(page.locator('g[role="button"] rect').first()).toHaveAttribute("x", "140");

  // Settle: the Saving... indicator only clears in the finally-block after
  // the whole serialized chain (including any trailing save) has finished.
  await expect(page.getByRole("button", { name: "Saving..." })).toBeHidden();

  // The race this spec exists for: at most ONE PUT in flight, ever. The old
  // per-keypress path deterministically reached 2-4 under this stub delay.
  expect(maxInFlight, "concurrent PUTs during the key-repeat burst").toBe(1);
  // Coalescing actually engaged: later presses queued behind the in-flight
  // request instead of firing their own immediately.
  expect(putBodies.length, "PUTs fired for the four-press burst").toBeGreaterThanOrEqual(2);
  expect(putBodies.length, "coalescing must drop PUTs, not add them").toBeLessThanOrEqual(4);
  // The trailing save carries the final position, so the last response the
  // page can apply is the newest snapshot — never an earlier one.
  expect(lastPutPos(), "last PUT must carry the final position").toEqual({ x: 140, y: 100 });
  // And the rendered canvas matches it (no stale-response rollback).
  await expect(page.locator('g[role="button"] rect').first()).toHaveAttribute("x", "140");
  await expect(page.locator('g[role="button"] rect').first()).toHaveAttribute("y", "100");
});

test("a failed save drops its queued snapshot instead of replaying it stale", async () => {
  // First PUT fails after 400ms (long enough for two more presses to queue
  // behind it); every later PUT succeeds quickly.
  resetSaveRecords({ firstDelayMs: 400, laterDelayMs: 100, failFirst: true });
  const node = await openBuilderDag();

  await node.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Node Properties", { exact: false }).first()).toBeVisible();

  // nudge 1 → PUT(x=110) that will fail; nudges 2 and 3 arrive inside its
  // 400ms window, so they queue: pending becomes x=120 then x=130.
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => firstPutFailed, "the stubbed save failure landed").toBe(true);
  // The failure has been fully processed (Saving... cleared → the finally
  // block ran) before the next nudge, so the next press starts a fresh chain.
  await expect(page.getByRole("button", { name: "Saving..." })).toBeHidden();

  // nudge 4 → fresh chain, PUT(x=140), which succeeds.
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("button", { name: "Saving..." })).toBeHidden();
  await expect.poll(() => putCompletions, "all PUTs settled").toBe(putBodies.length);

  // Exactly two PUTs happened: the failed x=110 and the retry x=140. The
  // stale x=130 queued behind the failure must have been DROPPED — replaying
  // it would PUT an out-of-date frame after the newer one and then roll the
  // canvas back to it.
  expect(putBodies.length, "failed save + one retry, no stale replay").toBe(2);
  expect(lastPutPos(), "retry carries the newest position").toEqual({ x: 140, y: 100 });
  const pos = await nodeRectPos();
  expect(pos, "canvas shows the newest position, not a stale replay").toEqual({ x: "140", y: "100" });
});
