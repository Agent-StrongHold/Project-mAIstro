/**
 * The workspace tab strip and the create-workspace persona picker render
 * structured skeletons while their reads are pending, and a failed read
 * terminates into an error state — not the empty state (#1421).
 *
 * Two defects this pins down. While GET /v1/workspaces was in flight the
 * strip rendered `null`: the toolbar row collapsed, then popped open. And
 * any failure — 401 refusal, 500, transport — was swallowed into
 * `workspaces: []`, so an unreachable list was indistinguishable from an
 * account with no workspaces. The persona picker had the second defect
 * while its options loaded: "No personas available" showed for a request
 * that had not answered yet.
 *
 * The harness bundles the shipped WorkspaceContext + WorkspaceTabs (same
 * E2E_SRC_ROOT arrangement as dashboard-metrics-states.spec.ts). The two
 * reads are scripted through `page.route` — app-shell-loading.spec.ts's
 * mechanism — so a request can be parked and released deterministically,
 * including a same-URL hold with a later request answered first, which the
 * stale-response case requires.
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

type Workspace = {
  id: string;
  name: string;
  persona_template_id: string;
  theme_id: string;
  voice_tone_override: string | null;
  members: unknown[];
  tool_bindings: unknown[];
  active: boolean;
};

const workspace = (id: string, name: string): Workspace => ({
  id,
  name,
  persona_template_id: "greenhouse",
  theme_id: "default",
  voice_tone_override: null,
  members: [],
  tool_bindings: [],
  active: true,
});

const PERSONAS = [
  { id: "greenhouse", display_name: "Greenhouse", tagline: "Warm, patient, growth-minded" },
  { id: "slate", display_name: "Slate", tagline: "Dry, precise, minimal" },
];

let context: BrowserContext;
let page: Page;
let server: Server;
let harnessUrl: string;
let workDir: string;

const EVIDENCE_DIR = join("test-results", "skeleton-evidence", "workspace-tabs");

// ── scripted reads (page.route; each request shifts the next entry) ──────
type Scripted = { status: number; payload: unknown; hold?: boolean };
let workspacesQueue: Scripted[] = [];
let workspacesHold: Promise<void> = Promise.resolve();
let workspacesRelease: (() => void) | null = null;
let templatesQueue: Scripted[] = [];
let templatesHold: Promise<void> = Promise.resolve();
let templatesRelease: (() => void) | null = null;

function scriptWorkspaces(...responses: Scripted[]) {
  workspacesQueue = responses;
}
function armWorkspacesHold() {
  workspacesHold = new Promise<void>((resolve) => { workspacesRelease = resolve; });
}
function releaseWorkspaces() {
  workspacesRelease?.();
  workspacesRelease = null;
  workspacesHold = Promise.resolve();
}
function scriptTemplates(...responses: Scripted[]) {
  templatesQueue = responses;
}
function armTemplatesHold() {
  templatesHold = new Promise<void>((resolve) => { templatesRelease = resolve; });
}

async function startHarness(browser: Browser): Promise<void> {
  workDir = await mkdtemp(join(tmpdir(), "maistro-wstabs-"));
  const entry = join(workDir, "ws-tabs-harness.tsx");
  const bundle = join(workDir, "ws-tabs-harness.js");

  await writeFile(
    entry,
    `import React from "react";
import { createRoot } from "react-dom/client";
import { WorkspaceProvider, useWorkspaces } from ${JSON.stringify(`${SRC_ROOT}/frontend/src/context/WorkspaceContext.tsx`)};
import { WorkspaceTabs } from ${JSON.stringify(`${SRC_ROOT}/frontend/src/components/WorkspaceTabs.tsx`)};

// The refresh buttons drive the provider's refresh() directly, so the
// stale-response ordering can be scripted from the test.
function RefreshControls() {
  const { refresh } = useWorkspaces();
  return (
    <div>
      <button id="refresh-held" onClick={() => void refresh()}>refresh-held</button>
      <button id="refresh-quick" onClick={() => void refresh()}>refresh-quick</button>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <WorkspaceProvider>
    <WorkspaceTabs />
    <RefreshControls />
  </WorkspaceProvider>,
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
    // /v1/workspaces* never reaches the server: page.route scripts it.
    if (path.endsWith("harness.js")) {
      response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      response.end(await import("node:fs/promises").then((m) => m.readFile(bundle)));
      return;
    }
    if (path === "/index.css") {
      // The shipped stylesheet, so the skeleton states under test are the
      // styled ones (pulse + reduced-motion guard), not bare divs.
      response.writeHead(200, { "content-type": "text/css; charset=utf-8" });
      response.end(
        await import("node:fs/promises").then((m) => m.readFile(`${SRC_ROOT}/frontend/src/index.css`)),
      );
      return;
    }
    if (path === "/" || path === "/index.html") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(
        '<!doctype html><html><head><meta charset="utf-8"><title>Workspace tabs test</title>' +
          '<link rel="stylesheet" href="/index.css"></head>' +
          '<body><div id="root"></div><script type="module" src="/ws-tabs-harness.js"></script></body></html>',
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
    throw new Error("workspace tabs harness did not bind a TCP port");
  }
  harnessUrl = `http://127.0.0.1:${address.port}`;

  context = await browser.newContext();
  page = await context.newPage();

  const fulfillScripted = async (route: { fulfill: (opts: { status: number; contentType: string; body: string }) => Promise<void> }, next: Scripted | undefined) => {
    if (!next) {
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "no scripted response" }) });
      return;
    }
    await route.fulfill({
      status: next.status,
      contentType: "application/json",
      body: JSON.stringify(next.status === 200 ? next.payload : { detail: "scripted" }),
    });
  };

  await page.route("**/v1/workspaces", async (route) => {
    const next = workspacesQueue.shift();
    if (next?.hold) await workspacesHold;
    await fulfillScripted(route, next);
  });
  await page.route("**/v1/workspaces/persona-templates", async (route) => {
    const next = templatesQueue.shift();
    if (next?.hold) await templatesHold;
    await fulfillScripted(route, next);
  });
}

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

test("the pending workspace list renders a sized tab-strip skeleton", async () => {
  scriptWorkspaces({ status: 200, payload: [workspace("ws-a", "Alpha"), workspace("ws-b", "Beta")], hold: true });
  armWorkspacesHold();
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });

  const skeleton = page.getByTestId("workspace-tabs-skeleton");
  await expect(skeleton).toBeVisible();
  await expect(skeleton).toHaveAttribute("aria-busy", "true");
  await expect(skeleton).toHaveAttribute("aria-label", "Loading workspaces");
  const pills = skeleton.locator(".workspace-tab-skeleton");
  expect(await pills.count()).toBeGreaterThan(0);
  for (const pill of await pills.all()) {
    const box = await pill.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThan(0);
    expect(box!.width).toBeGreaterThan(0);
  }
  // Not the empty state, and no tab names the request has not delivered.
  await expect(page.locator(".workspace-empty")).toHaveCount(0);
  await expect(page.locator(".workspace-tab", { hasText: "Alpha" })).toHaveCount(0);

  await mkdir(EVIDENCE_DIR, { recursive: true });
  await page.screenshot({ path: join(EVIDENCE_DIR, "tabs-loading.png"), fullPage: true });
});

test("releasing the list swaps the skeleton for the real tabs", async () => {
  releaseWorkspaces();
  await expect(page.locator(".workspace-tab", { hasText: "Alpha" })).toBeVisible();
  await expect(page.locator(".workspace-tab", { hasText: "Beta" })).toBeVisible();
  await expect(page.getByTestId("workspace-tabs-skeleton")).toHaveCount(0);
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
  await page.screenshot({ path: join(EVIDENCE_DIR, "tabs-resolved.png"), fullPage: true });
});

test("an empty list shows the genuine empty state, not a skeleton", async () => {
  scriptWorkspaces({ status: 200, payload: [] });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".workspace-empty")).toBeVisible();
  await expect(page.getByTestId("workspace-tabs-skeleton")).toHaveCount(0);
});

test("a failed read terminates into an error state with retry, not the empty state", async () => {
  scriptWorkspaces({ status: 500, payload: [] });
  await page.reload({ waitUntil: "domcontentloaded" });
  const alert = page.locator(".workspace-tab-error");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(/couldn't load your workspaces/i);
  await expect(page.locator(".workspace-empty")).toHaveCount(0);
  await expect(page.getByTestId("workspace-tabs-skeleton")).toHaveCount(0);

  // Retry re-runs the same read and recovers into the tabs.
  scriptWorkspaces({ status: 200, payload: [workspace("ws-a", "Alpha")] });
  await alert.getByRole("button", { name: "Retry" }).click();
  await expect(page.locator(".workspace-tab", { hasText: "Alpha" })).toBeVisible();
  await expect(page.locator(".workspace-tab-error")).toHaveCount(0);
});

test("an auth refusal ends in the same error state, never a fake empty account", async () => {
  scriptWorkspaces({ status: 401, payload: [] });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".workspace-tab-error")).toBeVisible();
  await expect(page.locator(".workspace-empty")).toHaveCount(0);
  await expect(page.getByTestId("workspace-tabs-skeleton")).toHaveCount(0);
});

test("a stale superseded refresh cannot replace the newer list", async () => {
  // Loaded state: one tab. The next refresh is held, so a second (quick)
  // refresh can complete first; the quick one carries the NEWER list.
  scriptWorkspaces({ status: 200, payload: [workspace("ws-a", "Alpha")] });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByRole("tab", { name: "Alpha" })).toBeVisible();

  scriptWorkspaces(
    { status: 200, payload: [workspace("ws-a", "Alpha"), workspace("ws-b", "Beta")], hold: true },
    { status: 200, payload: [workspace("ws-a", "Alpha"), workspace("ws-b", "Beta"), workspace("ws-c", "Gamma")] },
  );
  armWorkspacesHold();
  await page.locator("#refresh-held").click();
  await page.locator("#refresh-quick").click();
  await expect(page.getByRole("tab", { name: "Gamma" })).toBeVisible();
  // The held (older, sequenced-first) answer carries the two-tab list; if it
  // were applied after the newer answer, Gamma would disappear.
  releaseWorkspaces();
  await page.waitForTimeout(300);
  await expect(page.getByRole("tab", { name: "Gamma" })).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(3);
});

test("the persona picker shows sized placeholders while its options load", async () => {
  scriptTemplates({ status: 200, payload: PERSONAS, hold: true });
  armTemplatesHold();
  await page.getByRole("button", { name: "New workspace" }).click();

  const skeleton = page.getByTestId("persona-skeleton");
  await expect(skeleton).toBeVisible();
  await expect(skeleton).toHaveAttribute("aria-busy", "true");
  const rows = skeleton.locator(".workspace-persona-skeleton-row");
  expect(await rows.count()).toBeGreaterThan(0);
  for (const row of await rows.all()) {
    const box = await row.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThan(0);
    expect(box!.width).toBeGreaterThan(0);
  }
  // "No personas available" is a settled answer, not a pending one.
  await expect(page.locator(".workspace-persona-none", { hasText: "No personas available" })).toHaveCount(0);

  await mkdir(EVIDENCE_DIR, { recursive: true });
  await page.screenshot({ path: join(EVIDENCE_DIR, "persona-loading.png"), fullPage: true });

  templatesRelease?.();
  templatesHold = Promise.resolve();
  await expect(page.locator(".workspace-persona-option", { hasText: "Greenhouse" })).toBeVisible();
  await expect(page.locator(".workspace-persona-option", { hasText: "Slate" })).toBeVisible();
  await expect(page.getByTestId("persona-skeleton")).toHaveCount(0);
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
  await page.screenshot({ path: join(EVIDENCE_DIR, "persona-resolved.png"), fullPage: true });
});

test("a failed persona read settles into the degraded picker, not a permanent skeleton", async () => {
  // Close the form the previous test left open, then reopen against a
  // scripted failing read.
  await page.getByRole("button", { name: "New workspace" }).click();
  await expect(page.getByTestId("persona-skeleton")).toHaveCount(0);
  scriptTemplates({ status: 500, payload: [] });
  await page.getByRole("button", { name: "New workspace" }).click();
  await expect(page.locator(".workspace-persona-none", { hasText: "No personas available" })).toBeVisible();
  await expect(page.getByTestId("persona-skeleton")).toHaveCount(0);
});
