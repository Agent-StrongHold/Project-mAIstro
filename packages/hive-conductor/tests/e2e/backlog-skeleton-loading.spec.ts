/**
 * The Backlog board, list and detail modal render structured skeletons while
 * their reads are pending, and a failed initial read terminates into an
 * error state with retry — not four "empty" columns (#1421).
 *
 * Two defects this pins down. While GET /v1/backlog was in flight the board
 * rendered its zero-state: every column said "empty" and the header said
 * "0 items", so a hung request was indistinguishable from an empty backlog.
 * And the detail modal kept the previously opened item's content (or
 * nothing at all) while the next item loaded — worse, opening item B while
 * item A's read was still in flight let A's late response overwrite the
 * modal with the wrong item.
 *
 * The harness bundles the shipped Backlog.tsx (same E2E_SRC_ROOT
 * arrangement as dashboard-metrics-states.spec.ts) and scripts every
 * endpoint from this file, so requests can be held open and released
 * deterministically.
 */

import { build } from "esbuild";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

// CI mounts the repo at /tests (tests/Dockerfile.playwright); locally point
// E2E_SRC_ROOT at the worktree and E2E_NODE_PATHS at ':'-joined module dirs.
const SRC_ROOT = process.env.E2E_SRC_ROOT || "/tests";
const NODE_PATHS = (process.env.E2E_NODE_PATHS || "/tests/node_modules").split(":");

type BacklogItem = {
  id: string;
  title: string;
  description: string;
  status: "todo" | "in_progress" | "blocked" | "done";
  priority: number;
  rank: number;
  pinned: boolean;
  paused: boolean;
  paused_reason: string | null;
  archived: boolean;
  blocked_reason: string | null;
  parent_id: string | null;
  dependencies: string[];
  acceptance_evidence: string;
  source: string;
  risk: "low" | "medium" | "high";
  autonomy_mode: string;
  goal_id: string | null;
  goal_revision: number | null;
  owner_id: string;
  workspace_id: string | null;
  version: number;
  provenance: { actor: string; action: string; at: string; detail: Record<string, unknown> }[];
  created_at: string;
  updated_at: string;
};

const item = (id: string, title: string, status: BacklogItem["status"]): BacklogItem => ({
  id,
  title,
  description: `${title} description`,
  status,
  priority: 2,
  rank: 1,
  pinned: false,
  paused: false,
  paused_reason: null,
  archived: false,
  blocked_reason: null,
  parent_id: null,
  dependencies: [],
  acceptance_evidence: "evidence",
  source: "tests",
  risk: "low",
  autonomy_mode: "autonomous",
  goal_id: null,
  goal_revision: null,
  owner_id: "admin",
  workspace_id: null,
  version: 3,
  provenance: [{ actor: "admin", action: "created", at: new Date().toISOString(), detail: {} }],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
});

const detailFor = (it: BacklogItem) => ({
  item: it,
  dependencies: [],
  dependents: [],
  children: [],
  authority: { canonical_service: "backlog", ui_authoritative: false, cutover_issue: 102 },
});

const AUTHORITY = { canonical_service: "backlog", ui_authoritative: false, cutover_issue: 102 };

let context: BrowserContext;
let page: Page;
let server: Server;
let harnessUrl: string;
let workDir: string;

const EVIDENCE_DIR = join("test-results", "skeleton-evidence", "backlog");

// ── scripted backend state ────────────────────────────────────────────────
type ListResponse = { status: number; payload: unknown; hold?: boolean };
let listQueue: ListResponse[] = [];
let listRelease: (() => void) | null = null;
// Per-item detail scripts; an id without a script answers 200 immediately.
let detailQueue: Record<string, ListResponse> = {};
let detailRelease: (() => void) | null = null;

function scriptList(...responses: ListResponse[]) {
  listQueue = responses;
}
function scriptDetail(id: string, response: ListResponse) {
  detailQueue[id] = response;
}
function releaseList() {
  listRelease?.();
  listRelease = null;
}
function releaseDetail() {
  detailRelease?.();
  detailRelease = null;
}

async function startHarness(browser: Browser): Promise<void> {
  workDir = await mkdtemp(join(tmpdir(), "maistro-backlog-"));
  const entry = join(workDir, "backlog-harness.tsx");
  const bundle = join(workDir, "backlog-harness.js");

  await writeFile(
    entry,
    `import React from "react";
import { createRoot } from "react-dom/client";
import Backlog from ${JSON.stringify(`${SRC_ROOT}/frontend/src/pages/Backlog.tsx`)};
import { ToastProvider } from ${JSON.stringify(`${SRC_ROOT}/frontend/src/components/shared.tsx`)};

createRoot(document.getElementById("root")!).render(
  <ToastProvider>
    <Backlog />
  </ToastProvider>,
);
`,
    "utf8",
  );

  await build({
    entryPoints: [entry],
    outfile: bundle,
    bundle: true,
    platform: "browser",
    format: "esm",
    jsx: "automatic",
    define: {
      "process.env.NODE_ENV": '"test"',
      "import.meta.env.DEV": "false",
      "import.meta.env.VITE_DEBUG_API": '"false"',
      "import.meta.env.VITE_JIRA_BASE_URL": '""',
    },
    nodePaths: NODE_PATHS,
    logLevel: "silent",
  });

  server = createServer(async (request, response) => {
    const path = (request.url || "/").split("?")[0];

    if (path === "/v1/backlog" && request.method === "GET") {
      const next = listQueue.shift();
      if (!next) {
        response.writeHead(500, { "content-type": "application/json" });
        response.end(JSON.stringify({ detail: "no scripted response" }));
        return;
      }
      if (next.hold) {
        await new Promise<void>((resolve) => { listRelease = resolve; });
      }
      response.writeHead(next.status, { "content-type": "application/json" });
      response.end(JSON.stringify(next.status === 200 ? next.payload : { detail: "scripted" }));
      return;
    }
    const detailMatch = path.match(/^\/v1\/backlog\/([^/]+)$/);
    if (detailMatch && request.method === "GET") {
      const id = decodeURIComponent(detailMatch[1]);
      const next = detailQueue[id];
      if (next?.hold) {
        await new Promise<void>((resolve) => { detailRelease = resolve; });
      }
      const status = next?.status ?? (next ? 200 : 404);
      const payload = status === 200 ? detailFor(item(id, `Item ${id}`, "todo")) : { detail: "scripted" };
      response.writeHead(status, { "content-type": "application/json" });
      response.end(JSON.stringify(payload));
      return;
    }
    if (path.endsWith("harness.js")) {
      response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      response.end(await import("node:fs/promises").then((m) => m.readFile(bundle)));
      return;
    }
    if (path === "/index.css") {
      // The shipped cascade in main.tsx's order (tokens → bridge →
      // index.css): without the theme files `.skeleton`'s var(--rule)
      // background never resolves and the harness paints transparent,
      // unstyled shapes, not the styled skeletons under test.
      const sheets = await Promise.all(
        [
          `${SRC_ROOT}/frontend/src/themes/workspace-tokens.css`,
          `${SRC_ROOT}/frontend/src/themes/workspace-bridge.css`,
          `${SRC_ROOT}/frontend/src/index.css`,
        ].map((file) => import("node:fs/promises").then((m) => m.readFile(file, "utf8"))),
      );
      response.writeHead(200, { "content-type": "text/css; charset=utf-8" });
      response.end(sheets.join("\n"));
      return;
    }
    if (path === "/" || path === "/index.html") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(
        '<!doctype html><html><head><meta charset="utf-8"><title>Backlog skeleton test</title>' +
          '<link rel="stylesheet" href="/index.css"></head>' +
          '<body><div id="root"></div><script type="module" src="/backlog-harness.js"></script></body></html>',
      );
      return;
    }
    response.writeHead(404, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: "not found", path }));
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("backlog harness did not bind a TCP port");
  }
  harnessUrl = `http://127.0.0.1:${address.port}`;

  context = await browser.newContext();
  page = await context.newPage();
}

const TWO_ITEMS = {
  items: [item("a-1", "Ship the skeleton", "todo"), item("a-2", "Review the board", "in_progress")],
  authority: AUTHORITY,
};

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  await startHarness(browser);
});

test.afterAll(async () => {
  await context.close();
  await new Promise<void>((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
  await rm(workDir, { recursive: true, force: true });
});

test("the pending board read renders a sized board skeleton, never the empty columns", async () => {
  scriptList({ status: 200, payload: TWO_ITEMS, hold: true });
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });

  const skeleton = page.getByTestId("backlog-skeleton");
  await expect(skeleton).toBeVisible();
  await expect(skeleton).toHaveAttribute("aria-busy", "true");
  await expect(skeleton).toHaveAttribute("aria-label", "Loading backlog");
  const shapes = skeleton.locator("[aria-hidden='true'] .skeleton");
  expect(await shapes.count()).toBeGreaterThan(0);
  for (const shape of await shapes.all()) {
    const box = await shape.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThan(0);
    expect(box!.width).toBeGreaterThan(0);
  }
  // Stable shell anchors: the page heading and the view switch stay put.
  await expect(page.getByRole("heading", { name: "Backlog", exact: true })).toBeVisible();
  await expect(page.getByText("board", { exact: true })).toBeVisible();
  // Not the zero state: no "empty" columns, no "0 items" in the header.
  await expect(skeleton.getByText("empty", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/0 items/)).toHaveCount(0);
  // No fake items.
  await expect(skeleton.getByText("Ship the skeleton")).toHaveCount(0);

  await mkdir(EVIDENCE_DIR, { recursive: true });
  await page.screenshot({ path: join(EVIDENCE_DIR, "board-loading.png"), fullPage: true });
});

test("releasing the list swaps the skeleton for the real board and keeps the authority notice", async () => {
  releaseList();
  await expect(page.locator(".card", { hasText: "Ship the skeleton" })).toBeVisible();
  await expect(page.getByTestId("backlog-skeleton")).toHaveCount(0);
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
  // The canonical-service/preview-authority notice is intact.
  await expect(page.getByText(/Preview surface — this board edits through the canonical backlog service/)).toBeVisible();
  await page.screenshot({ path: join(EVIDENCE_DIR, "board-resolved.png"), fullPage: true });
});

test("switching to list view while the read is pending shows the list skeleton", async () => {
  scriptList({ status: 200, payload: TWO_ITEMS, hold: true });
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("backlog-skeleton")).toBeVisible();
  await page.getByText("list", { exact: true }).click();
  await expect(page.getByTestId("backlog-skeleton")).toBeVisible();
  const shapes = page.getByTestId("backlog-skeleton").locator(".skeleton");
  const box = await shapes.first().boundingBox();
  expect(box!.height).toBeGreaterThan(0);
  expect(box!.width).toBeGreaterThan(0);
  await expect(page.getByText("backlog is empty")).toHaveCount(0);
  releaseList();
  await expect(page.locator(".card", { hasText: "Ship the skeleton" })).toBeVisible();
  await expect(page.getByTestId("backlog-skeleton")).toHaveCount(0);
});

test("an empty list shows the genuine empty state", async () => {
  scriptList({ status: 200, payload: { items: [], authority: AUTHORITY } });
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  // The settled zero state, distinct from the pending skeleton: the board
  // columns say "empty" (and the header counts 0 items) only once the read
  // has answered.
  await expect(page.getByText("empty", { exact: true })).toHaveCount(4);
  await expect(page.getByText(/0 items/)).toBeVisible();
  await expect(page.getByTestId("backlog-skeleton")).toHaveCount(0);
  // And in list view the hand-written empty line shows.
  await page.getByText("list", { exact: true }).click();
  await expect(page.getByText("backlog is empty — create the first item")).toBeVisible();
});

for (const boardFailureStatus of [500, 401] as const) {
  test(`a ${boardFailureStatus} from the board read terminates into an error state with retry`, async () => {
    scriptList({ status: boardFailureStatus, payload: {} });
    await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
    const alert = page.getByTestId("backlog-load-error");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/couldn't be loaded/i);
    // Never the zero state for a request that failed.
    await expect(page.getByText("backlog is empty")).toHaveCount(0);
    await expect(page.getByTestId("backlog-skeleton")).toHaveCount(0);

    scriptList({ status: 200, payload: TWO_ITEMS });
    await alert.getByRole("button", { name: "Retry" }).click();
    await expect(page.locator(".card", { hasText: "Ship the skeleton" })).toBeVisible();
    await expect(page.getByTestId("backlog-load-error")).toHaveCount(0);
  });
}

test("the opened item's detail region is a sized skeleton until its read lands", async () => {
  scriptList({ status: 200, payload: TWO_ITEMS });
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".card", { hasText: "Ship the skeleton" })).toBeVisible();

  scriptDetail("a-1", { status: 200, payload: detailFor(item("a-1", "Ship the skeleton", "todo")), hold: true });
  await page.locator(".card", { hasText: "Ship the skeleton" }).getByText("Ship the skeleton").click();

  const modal = page.locator("dialog[open]");
  await expect(modal).toBeVisible();
  const skeleton = modal.getByTestId("backlog-detail-skeleton");
  await expect(skeleton).toBeVisible();
  await expect(skeleton).toHaveAttribute("aria-busy", "true");
  const shapes = skeleton.locator(".skeleton");
  for (const shape of await shapes.all()) {
    const box = await shape.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThan(0);
    expect(box!.width).toBeGreaterThan(0);
  }
  // No fake fields while the read is open.
  await expect(modal.getByText("ACCEPTANCE EVIDENCE")).toHaveCount(0);

  await mkdir(EVIDENCE_DIR, { recursive: true });
  await page.screenshot({ path: join(EVIDENCE_DIR, "detail-loading.png"), fullPage: true });

  releaseDetail();
  await expect(modal.getByText("ACCEPTANCE EVIDENCE")).toBeVisible();
  await expect(modal.getByTestId("backlog-detail-skeleton")).toHaveCount(0);
  await expect(modal.locator("[aria-busy='true']")).toHaveCount(0);
  await page.screenshot({ path: join(EVIDENCE_DIR, "detail-resolved.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(modal).not.toBeVisible();
});

test("a stale detail answer cannot replace the newly opened item", async () => {
  // Open A; its read is held. Close, then open B, whose read answers fast.
  // A's late response must be dropped, not rendered over B.
  scriptDetail("a-1", { status: 200, payload: detailFor(item("a-1", "Stale A content", "todo")), hold: true });
  await page.locator(".card", { hasText: "Ship the skeleton" }).getByText("Ship the skeleton").click();
  const modal = page.locator("dialog[open]");
  await expect(modal.getByTestId("backlog-detail-skeleton")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(modal).not.toBeVisible();

  scriptDetail("a-2", { status: 200, payload: detailFor(item("a-2", "Fresh B content", "in_progress")) });
  await page.locator(".card", { hasText: "Review the board" }).getByText("Review the board").click();
  await expect(modal).toBeVisible();
  // B's read answers immediately, so the modal resolves straight onto it.
  await expect(modal.locator("h2", { hasText: "Item a-2" })).toBeVisible();
  await expect(modal.getByTestId("backlog-detail-skeleton")).toHaveCount(0);

  releaseDetail();
  // A's late answer — sequenced before B's open — is dropped whole: the
  // modal still shows B, and none of A's content appears.
  await page.waitForTimeout(300);
  await expect(modal.locator("h2", { hasText: "Item a-2" })).toBeVisible();
  await expect(modal.getByText("Stale A content")).toHaveCount(0);
  await expect(modal.locator("h2", { hasText: "Item a-1" })).toHaveCount(0);
  await page.keyboard.press("Escape");
});

test("a failed detail read closes the modal into the board, not a permanent skeleton", async () => {
  // The failure must be held open so the skeleton state is observable before
  // the terminal outcome: an immediate 500 races React's paint and can close
  // the modal before the skeleton is ever on screen (observed in the CI
  // image, 2026-10). This test mounts its own board from a freshly scripted
  // list read, so it runs the same serially and on its own.
  scriptList({ status: 200, payload: TWO_ITEMS });
  scriptDetail("a-1", { status: 500, payload: {}, hold: true });
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  await page.locator(".card", { hasText: "Ship the skeleton" }).getByText("Ship the skeleton").click();
  const modal = page.locator("dialog[open]");
  await expect(modal.getByTestId("backlog-detail-skeleton")).toBeVisible();
  releaseDetail();
  // The existing recovery state: a toast names the failure and the modal
  // closes back onto the board.
  await expect(page.locator(".toast, [role='status']", { hasText: "Couldn't load that item" }).first()).toBeVisible();
  await expect(modal).not.toBeVisible();
  await expect(page.getByTestId("backlog-detail-skeleton")).toHaveCount(0);
});
