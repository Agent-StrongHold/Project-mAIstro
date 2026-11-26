/**
 * E2E proof for #380: dashboard KPIs render measured values with provenance,
 * and zero / no-data / stale / unavailable / unauthorized / outage are all
 * visible states — never a plausible-looking placeholder 0.
 *
 * Like the widget spec beside it, this bundles the exact shipped
 * Dashboard.tsx into the Playwright image and mounts it on an ephemeral
 * localhost page. The harness server seeds /v1/dashboard/metrics with the
 * envelopes a real deployment would serve, so every state below is exercised
 * against the shipped rendering path.
 */

import { build } from "esbuild";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
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

const seedEnvelope = (over: Partial<Envelope> = {}): Envelope =>
  env({
    state: "ok",
    value: 7,
    unit: "runs",
    window: "today, since midnight",
    ...over,
  });

/** Non-zero seed data: every measured KPI carries a real number (#380). */
function seededMetrics(): Record<string, Envelope> {
  return {
    active_agents: seedEnvelope({ value: 4, unit: "agents", window: "current roster" }),
    runs_today: seedEnvelope({ value: 7, unit: "runs", window: "today, since midnight" }),
    avg_latency: seedEnvelope({
      value: 1523.4,
      unit: "ms",
      window: "trailing 1h of in-process chat observations (bounded at 10,000)",
    }),
    total_cost: seedEnvelope({ value: 1.2537, unit: "USD" }),
    invocations: seedEnvelope({
      value: 12,
      unit: "invocations",
      window: "process lifetime of in-process chat observations (bounded at 10,000)",
      latency_ms_p50: 1400,
      latency_ms_p95: 3100,
      tokens_in_total: 5400,
      tokens_out_total: 2100,
    }),
    ttft: env({
      state: "unavailable",
      unit: "ms",
      window: "n/a",
      reason: "TTFT telemetry is not recorded by this deployment",
    }),
    approval_rate: env({
      state: "unavailable",
      unit: "ratio",
      window: "n/a",
      reason: "approval decisions are not recorded, so no rate can be computed",
    }),
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
        { id: "kpi-ttft", type: "kpi", title: "TTFT", size: "1", config: { field: "ttft", sub: "p50 streaming" } },
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

/** What GET /v1/dashboard/metrics answers for the current test. */
let metricsStatus = 200;
let metricsPayload: Record<string, Envelope> = seededMetrics();
/** Artificial delay for the metrics reply, to catch the loading state. */
let metricsDelayMs = 0;

async function startHarness(browser: Browser): Promise<void> {
  workDir = await mkdtemp(join(tmpdir(), "maistro-kpi-"));
  const entry = join(workDir, "kpi-harness.tsx");
  const bundle = join(workDir, "kpi-harness.js");

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

    if (path === "/v1/dashboard/metrics") {
      const answer = () => {
        response.writeHead(metricsStatus, { "content-type": "application/json" });
        response.end(JSON.stringify(metricsStatus === 200 ? metricsPayload : { detail: "simulated outage" }));
      };
      if (metricsDelayMs > 0) setTimeout(answer, metricsDelayMs);
      else answer();
      return;
    }
    if (request.method === "GET" && path === "/v1/dashboard/layout") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify(LAYOUT));
      return;
    }
    if (request.method === "PUT" && path === "/v1/dashboard/layout") {
      for await (const _chunk of request) {
        // body ignored
      }
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true, revision: 1 }));
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
    if (path === "/kpi-harness.js") {
      response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      response.end(await import("node:fs/promises").then((m) => m.readFile(bundle)));
      return;
    }
    if (path === "/" || path === "/index.html") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(
        '<!doctype html><html><head><meta charset="utf-8"><title>KPI test</title></head>' +
          '<body><div id="root"></div><script type="module" src="/kpi-harness.js"></script></body></html>',
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
    throw new Error("KPI harness did not bind a TCP port");
  }
  harnessUrl = `http://127.0.0.1:${address.port}`;

  context = await browser.newContext();
  page = await context.newPage();
}

async function loadFresh(): Promise<void> {
  metricsStatus = 200;
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Active Agents")).toBeVisible();
}

function card(title: string) {
  return page.locator(".dashboard-widget-card", { hasText: title });
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

test("seeded non-zero KPIs render measured values with provenance", async () => {
  metricsPayload = seededMetrics();
  await loadFresh();

  const agents = card("Active Agents");
  await expect(agents.getByText(/^4$/)).toBeVisible();
  // Provenance: unit, window and freshness time are named next to the value,
  // and the tooltip names the authoritative query and scope.
  await expect(agents.locator('[title*="query: test-suite authoritative query"]')).toHaveCount(1);
  await expect(agents.getByText(/agents · roster ·/)).toBeVisible();

  const runs = card("Runs Today");
  await expect(runs.getByText(/^7$/)).toBeVisible();
  await expect(runs.getByText(/runs · today ·/)).toBeVisible();

  const latency = card("Avg Latency");
  await expect(latency.getByText("1.52s")).toBeVisible();

  const cost = card("Total Cost");
  await expect(cost.getByText("$1.25")).toBeVisible();

  // The invocations widget renders the seeded totals, not placeholders.
  const invocations = card("Invocations");
  await expect(invocations.getByText("12", { exact: true })).toBeVisible();
  await expect(invocations.getByText(/p50: 1400ms · p95: 3100ms/)).toBeVisible();
  await expect(invocations.getByText(/Tokens in: 5400 · out: 2100/)).toBeVisible();

  const donut = card("Cost by Agent");
  await expect(donut.getByText("$1.25")).toBeVisible();
});

test("unsupported KPIs are explicitly N/A with the reason", async () => {
  metricsPayload = seededMetrics();
  await loadFresh();

  const ttft = card("TTFT");
  await expect(ttft.getByText("N/A")).toBeVisible();
  await expect(ttft.getByText(/TTFT telemetry is not recorded/)).toBeVisible();
  // Distinct from a zero: no 0ms is rendered anywhere in the card.
  await expect(ttft.getByText(/0ms/)).toHaveCount(0);
});

test("an outage renders an error state, never zeros", async () => {
  metricsStatus = 500;
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  const runs = card("Runs Today");
  await expect(runs.getByText("⚠")).toBeVisible();
  await expect(runs.getByText(/Metrics source unreachable/)).toBeVisible();
  // And it does not quietly look like an idle deployment.
  await expect(runs.getByText(/^7$/)).toHaveCount(0);
  await expect(runs.getByText(/^0$/)).toHaveCount(0);
});

test("stale data is labelled with the value still visible", async () => {
  metricsPayload = seededMetrics();
  metricsPayload.runs_today = seedEnvelope({
    state: "stale",
    value: 3,
    unit: "runs",
    window: "today, since midnight",
    reason: "run history is in-memory and the process booted after local midnight",
  });
  await loadFresh();

  const runs = card("Runs Today");
  await expect(runs.getByText("STALE")).toBeVisible();
  await expect(runs.getByText(/^3$/)).toBeVisible();
  await expect(runs.getByText(/booted after local midnight/)).toBeVisible();
});

test("a measured zero and no-data render differently", async () => {
  metricsPayload = seededMetrics();
  metricsPayload.active_agents = seedEnvelope({
    value: 0,
    unit: "agents",
    window: "current roster",
  });
  metricsPayload.avg_latency = env({
    state: "no_data",
    value: null,
    unit: "ms",
    reason: "no chat activity observed for this principal yet",
  });
  await loadFresh();

  const agents = card("Active Agents");
  // A measured zero shows the digit with its provenance footer.
  await expect(agents.getByText(/^0$/)).toBeVisible();
  await expect(agents.getByText(/agents · roster ·/)).toBeVisible();

  const latency = card("Avg Latency");
  // No data shows an em-dash and says why — never a 0ms.
  await expect(latency.getByText("—", { exact: true })).toBeVisible();
  await expect(latency.getByText(/No data yet — no chat activity observed/)).toBeVisible();
  await expect(latency.getByText(/^0ms$/)).toHaveCount(0);
});

test("an unauthorized principal gets a sign-in state, not empty data", async () => {
  metricsStatus = 401;
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  const runs = card("Runs Today");
  await expect(runs.getByText("🔒")).toBeVisible();
  await expect(runs.getByText(/Sign-in required to read metrics/)).toBeVisible();
});

test("the in-flight request shows a loading state, then the value", async () => {
  metricsStatus = 200;
  metricsPayload = seededMetrics();
  metricsDelayMs = 800;
  await page.goto(harnessUrl, { waitUntil: "domcontentloaded" });
  const runs = card("Runs Today");
  await expect(runs.getByText(/Loading metrics…/)).toBeVisible();
  await expect(runs.getByText(/^7$/)).toBeVisible();
  metricsDelayMs = 0;
});
