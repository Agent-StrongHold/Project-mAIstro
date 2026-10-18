/**
 * The Dashboard's first paint is structured skeletons, not a pop (#1421).
 *
 * Two named reads stand between navigation and the dashboard's real content:
 * GET /v1/dashboard/layout (which widget grid to render) and
 * GET /v1/dashboard/metrics (what the KPI cards say). Both used to resolve
 * into fully-rendered replacements — the default widgets were on screen
 * first, then swapped for the server's; each KPI said "Loading metrics…" in
 * a text sentence before its number appeared — so every load visibly
 * collapsed and re-expanded. Now the pending layout renders a sized grid
 * skeleton matching the default layout's footprint, and each pending KPI
 * reserves its value/sub/footer geometry with aria-hidden shapes under an
 * aria-busy body.
 *
 * The harness bundles the shipped Dashboard.tsx (E2E_SRC_ROOT, same as
 * dashboard-metrics-states.spec.ts) and serves every endpoint from this
 * file, so each request can be held open deterministically and released —
 * no sleep-based screenshots.
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

type Envelope = Record<string, unknown>;

const env = (over: Partial<Envelope> = {}): Envelope => ({
  state: "ok",
  value: 0,
  unit: "",
  query: "test-suite authoritative query",
  scope: "user:demo",
  window: "trailing 1h of in-process chat observations (bounded at 10,000)",
  computed_at: new Date().toISOString(),
  last_update: new Date().toISOString(),
  reason: null,
  ...over,
});

function seededMetrics(): Record<string, Envelope> {
  return {
    active_agents: env({ value: 4, unit: "agents", window: "current roster" }),
    runs_today: env({ value: 7, unit: "runs", window: "today, since midnight" }),
    avg_latency: env({ value: 1523.4, unit: "ms" }),
    total_cost: env({ value: 1.2537, unit: "USD" }),
    approval_rate: env({ value: 0.5, unit: "ratio" }),
    ttft: env({ value: 900, unit: "ms" }),
  };
}

const LAYOUT = {
  tabs: [
    {
      name: "Overview",
      widgets: [
        { id: "kpi-agents", type: "kpi", title: "Active Agents", size: "1", config: { field: "active_agents", sub: "vs last hour" } },
        { id: "kpi-runs", type: "kpi", title: "Runs Today", size: "1", config: { field: "runs_today", sub: "vs yesterday" } },
        { id: "kpi-latency", type: "kpi", title: "Avg Latency", size: "1", config: { field: "avg_latency", sub: "vs last hour" } },
        { id: "kpi-cost", type: "kpi", title: "Total Cost", size: "1", config: { field: "total_cost", sub: "vs yesterday" } },
        { id: "invocations", type: "invocations", title: "Invocations", size: "3" },
        { id: "cost-donut", type: "cost-donut", title: "Cost by Agent", size: "1" },
      ],
    },
  ],
  activeTab: 0,
};

let context: BrowserContext;
let page: Page;
let server: Server;
let harnessUrl: string;
let workDir: string;

/** Screenshot evidence (gitignored under test-results/). */
const EVIDENCE_DIR = join("test-results", "skeleton-evidence", "dashboard");

// ── scripted backend state ────────────────────────────────────────────────
let metricsStatus = 200;
let metricsPayload: Record<string, Envelope> = seededMetrics();
let layoutStatus = 200;
let layoutPayload: Record<string, unknown> = LAYOUT;
// A held endpoint parks its request until released; later requests pass.
let metricsGate: Promise<void> = Promise.resolve();
let releaseMetrics: (() => void) | null = null;
let layoutGate: Promise<void> = Promise.resolve();
let releaseLayout: (() => void) | null = null;

function holdMetrics() {
  metricsGate = new Promise<void>((resolve) => { releaseMetrics = resolve; });
}
function flushMetrics() {
  releaseMetrics?.();
  metricsGate = Promise.resolve();
}
function holdLayout() {
  layoutGate = new Promise<void>((resolve) => { releaseLayout = resolve; });
}
function flushLayout() {
  releaseLayout?.();
  layoutGate = Promise.resolve();
}

async function startHarness(browser: Browser): Promise<void> {
  workDir = await mkdtemp(join(tmpdir(), "maistro-dash-skel-"));
  const entry = join(workDir, "dash-skel-harness.tsx");
  const bundle = join(workDir, "dash-skel-harness.js");

  await writeFile(
    entry,
    `import React from "react";
import { createRoot } from "react-dom/client";
import Dashboard from ${JSON.stringify(`${SRC_ROOT}/frontend/src/pages/Dashboard.tsx`)};

createRoot(document.getElementById("root")!).render(<Dashboard />);
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

    if (path === "/v1/dashboard/layout" && request.method === "GET") {
      await layoutGate;
      response.writeHead(layoutStatus, { "content-type": "application/json" });
      response.end(JSON.stringify(layoutStatus === 200 ? layoutPayload : { detail: "simulated outage" }));
      return;
    }
    if (path === "/v1/dashboard/layout" && request.method === "PUT") {
      for await (const _chunk of request) {
        // body ignored
      }
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true, revision: 1 }));
      return;
    }
    if (path === "/v1/dashboard/metrics") {
      await metricsGate;
      response.writeHead(metricsStatus, { "content-type": "application/json" });
      response.end(JSON.stringify(metricsStatus === 200 ? metricsPayload : { detail: "simulated outage" }));
      return;
    }
    if (path === "/v1/agents") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end("[]");
      return;
    }
    if (path === "/v1/setup-checklist") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ items: [] }));
      return;
    }
    if (path.endsWith("harness.js")) {
      response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      response.end(await import("node:fs/promises").then((m) => m.readFile(bundle)));
      return;
    }
    if (path === "/index.css") {
      // The shipped cascade in main.tsx's order (tokens → bridge →
      // index.css): `.skeleton`'s pulse and its prefers-reduced-motion guard
      // live in index.css, but its `background: var(--rule)` only resolves
      // once the theme files are in the cascade — without them the harness
      // paints transparent, unstyled shapes, not the styled skeletons under
      // test.
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
        '<!doctype html><html><head><meta charset="utf-8"><title>Dashboard skeleton test</title>' +
          '<link rel="stylesheet" href="/index.css"></head>' +
          '<body><div id="root"></div><script type="module" src="/dash-skel-harness.js"></script></body></html>',
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
    throw new Error("dashboard skeleton harness did not bind a TCP port");
  }
  harnessUrl = `http://127.0.0.1:${address.port}`;

  context = await browser.newContext();
  page = await context.newPage();
}

function resetBackend() {
  flushLayout();
  flushMetrics();
  metricsStatus = 200;
  metricsPayload = seededMetrics();
  layoutStatus = 200;
  layoutPayload = LAYOUT;
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

test("the pending layout renders a sized grid skeleton and resolves into the real grid without collapsing the page", async () => {
  resetBackend();
  holdLayout();
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });

  const skeleton = page.getByTestId("dashboard-skeleton");
  await expect(skeleton).toBeVisible();
  await expect(skeleton).toHaveAttribute("aria-busy", "true");
  // One meaningful pending announcement for the region; the shapes
  // themselves are aria-hidden.
  await expect(skeleton).toHaveAttribute("aria-label", "Loading dashboard");

  // Sized placeholders: every shape is visible with nonzero geometry.
  const shapes = skeleton.locator("[aria-hidden='true'] .skeleton");
  expect(await shapes.count()).toBeGreaterThan(0);
  for (const shape of await shapes.all()) {
    await expect(shape).toBeVisible();
    const box = await shape.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThan(0);
    expect(box!.width).toBeGreaterThan(0);
  }
  // The region reserves substantial height, so the resolved grid cannot
  // collapse into it.
  const skeletonBox = await skeleton.boundingBox();
  expect(skeletonBox!.height).toBeGreaterThan(200);

  // Stable shell anchors stay on screen and usable while the data is
  // pending: the page heading and the tab strip.
  const heading = page.getByRole("heading", { name: "Live Operations" });
  const overviewTab = page.getByRole("button", { name: "Overview" });
  await expect(heading).toBeVisible();
  await expect(overviewTab).toBeVisible();
  const headingBefore = await heading.boundingBox();
  const tabBefore = await overviewTab.boundingBox();
  // No fake content: no widget card, no metric number, no empty state.
  await expect(page.locator(".dashboard-widget-card")).toHaveCount(0);
  await expect(skeleton.getByText("Active Agents")).toHaveCount(0);

  await mkdir(EVIDENCE_DIR, { recursive: true });
  await page.screenshot({ path: join(EVIDENCE_DIR, "layout-loading-desktop.png"), fullPage: true });

  // Release: the skeleton is replaced by the server's widgets, the busy
  // state clears, and the shell anchors do not move.
  flushLayout();
  const firstCard = page.locator(".dashboard-widget-card").first();
  await expect(firstCard).toBeVisible();
  await expect(skeleton).toHaveCount(0);
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);

  const headingAfter = await heading.boundingBox();
  const tabAfter = await overviewTab.boundingBox();
  expect(headingAfter!.y).toBeCloseTo(headingBefore!.y, 0);
  expect(tabAfter!.y).toBeCloseTo(tabBefore!.y, 0);

  // Same footprint, roughly: the grid did not collapse to nothing nor
  // balloon. A wide band, not a machine-speed threshold — the point is that
  // the placeholder reserved the region's dimensions (#1421 acceptance 3).
  const cardBox = await firstCard.boundingBox();
  expect(cardBox!.height).toBeGreaterThan(0);
  expect(skeletonBox!.height).toBeGreaterThan(cardBox!.height * 0.5);

  // Metrics answered while the layout was held, so the KPI values are
  // already on screen: no second pop.
  await expect(page.locator(".dashboard-widget-card", { hasText: "Runs Today" }).getByText(/^7$/)).toBeVisible();
  await page.screenshot({ path: join(EVIDENCE_DIR, "layout-resolved-desktop.png"), fullPage: true });
});

test("a failed layout read settles into the default dashboard, not a permanent skeleton", async () => {
  resetBackend();
  layoutStatus = 500;
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });

  await expect(page.getByTestId("dashboard-skeleton")).toHaveCount(0);
  // The long-standing recovery state: the editable default layout.
  await expect(page.locator(".dashboard-widget-card").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live Operations" })).toBeVisible();
});

for (const layoutFailureStatus of [401, 500] as const) {
  test(`a ${layoutFailureStatus} from the layout read terminates the skeleton the same way`, async () => {
    resetBackend();
    layoutStatus = layoutFailureStatus;
    await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("dashboard-skeleton")).toHaveCount(0);
    await expect(page.locator(".dashboard-widget-card").first()).toBeVisible();
  });
}

test("pending metrics render sized KPI skeletons, then the measured values", async () => {
  resetBackend();
  holdMetrics();
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });

  // The layout resolved, so the cards exist; their bodies are skeletons.
  const runs = page.locator(".dashboard-widget-card", { hasText: "Runs Today" });
  await expect(runs).toBeVisible();
  const loading = runs.getByTestId("kpi-loading");
  await expect(loading).toBeVisible();
  await expect(loading).toHaveAttribute("aria-busy", "true");
  const shapes = loading.locator("[aria-hidden='true'] .skeleton");
  expect(await shapes.count()).toBeGreaterThan(0);
  for (const shape of await shapes.all()) {
    const box = await shape.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThan(0);
    expect(box!.width).toBeGreaterThan(0);
  }
  // No fake metrics while the request is open.
  await expect(runs.getByText(/^7$/)).toHaveCount(0);

  await mkdir(EVIDENCE_DIR, { recursive: true });
  await page.screenshot({ path: join(EVIDENCE_DIR, "metrics-loading-desktop.png"), fullPage: true });

  flushMetrics();
  await expect(runs.getByText(/^7$/)).toBeVisible();
  await expect(loading).toHaveCount(0);
  await expect(runs.locator("[aria-busy='true']")).toHaveCount(0);
  await page.screenshot({ path: join(EVIDENCE_DIR, "metrics-resolved-desktop.png"), fullPage: true });
});

test("an empty metrics answer shows the genuine no-report state, not a skeleton", async () => {
  resetBackend();
  metricsPayload = {};
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  const runs = page.locator(".dashboard-widget-card", { hasText: "Runs Today" });
  await expect(runs.getByText(/the metrics source did not report it/)).toBeVisible();
  await expect(runs.getByTestId("kpi-loading")).toHaveCount(0);
});

test("KPI skeleton shapes only pulse when the OS allows motion", async () => {
  resetBackend();
  holdMetrics();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  const shape = page.getByTestId("kpi-loading").locator("[aria-hidden='true'] .skeleton").first();
  await expect(shape).toBeVisible();
  await expect(shape).toHaveCSS("animation-name", "none");

  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const shapeAgain = page.getByTestId("kpi-loading").locator("[aria-hidden='true'] .skeleton").first();
  await expect(shapeAgain).toBeVisible();
  await expect(shapeAgain).toHaveCSS("animation-name", "hc-skeleton-pulse");
  flushMetrics();
});

test("navigating away mid-load is clean, and a fresh load renders", async () => {
  test.info().annotations.push({ description: "no uncaught page errors across the abandonment (#1421 acceptance 5)", type: "note" });
  resetBackend();
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  holdLayout();
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("dashboard-skeleton")).toBeVisible();
  // Walk away while the request is still parked.
  await page.goto("about:blank");
  flushLayout();
  expect(pageErrors).toEqual([]);

  // Come back: a fresh load renders the resolved dashboard.
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".dashboard-widget-card").first()).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test("the skeleton holds its geometry at phone width and resolves into the grid", async () => {
  resetBackend();
  await page.setViewportSize({ width: 390, height: 844 });
  holdLayout();
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  const skeleton = page.getByTestId("dashboard-skeleton");
  await expect(skeleton).toBeVisible();
  const shape = skeleton.locator("[aria-hidden='true'] .skeleton").first();
  await expect(shape).toBeVisible();
  const box = await shape.boundingBox();
  expect(box!.height).toBeGreaterThan(0);
  expect(box!.width).toBeGreaterThan(0);
  await page.screenshot({ path: join(EVIDENCE_DIR, "layout-loading-narrow.png"), fullPage: true });

  flushLayout();
  await expect(page.locator(".dashboard-widget-card").first()).toBeVisible();
  await page.screenshot({ path: join(EVIDENCE_DIR, "layout-resolved-narrow.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 720 });
});
