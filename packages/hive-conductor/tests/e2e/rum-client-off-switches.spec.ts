/**
 * The RUM reporter's off-switches and failure bounds, in a real browser (#1420).
 *
 * Acceptance check 4's client half: disabled collection sends nothing, a
 * sampled-out session sends nothing, collector rejection can neither break
 * rendering nor trigger unbounded retries/buffering, and an unsupported
 * performance API degrades to the documented `load` fallback without
 * throwing. `rum-telemetry.spec.ts` proves these functions' redaction rules
 * and the enabled live path; this spec proves the reporter itself — which is
 * why it bundles the shipped `lib/rum.ts` rather than re-implementing it.
 *
 * The reporter is a module-level singleton initialized once per page load
 * from build-time env, so each scenario compiles its own bundle of the same
 * shipped module with its `import.meta.env` baked by esbuild `define` (the
 * same mechanism widget-capabilities.spec.ts uses for the Dashboard), then
 * loads it into a fresh page. A scenario-name build id tells the harness's
 * one collector endpoint which scenario is posting, so the breaker scenario
 * can be answered 500 while the others get 202 — the collector's documented
 * disabled answer, which still counts as delivered for the reporter.
 */

import { build } from "esbuild";
import { expect, test, type Browser, type BrowserContext } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { MAX_BATCH_EVENTS, type RumEnvelope } from "../../frontend/src/lib/rumSchema";

const SRC_ROOT = process.env.E2E_SRC_ROOT || "/tests";
const NODE_PATHS = [process.env.E2E_NODE_PATHS || "/tests/node_modules"];
const COLLECT_PATH = "/v1/rum/events";
/** Anything identifying; must survive normalizeApiPath as "/v1/agents/*". */
const RAW_AGENT_ID = "a1e40b7c-9931-4f0e-8d5c-77b2aa01fed9";

interface Scenario {
  name: string;
  /**
   * Vite env baked into the bundle as the whole `import.meta.env` object.
   * The module reads env through `(import.meta).env ?? {}` into one variable,
   * so per-key defines ("import.meta.env.VITE_RUM_ENABLED") would never be
   * seen — the object itself must be defined, which also keeps the module's
   * defensive read path (and its `?? {}` fallback) the code that runs.
   * Absent keys stay undefined, exactly like a Vite build without them.
   */
  env: Record<string, string>;
  /** Runs before any page script, for the unsupported-API scenario. */
  initScript?: string;
}

const ENABLED_BASE = { VITE_RUM_ENABLED: "true" };

const scenarios: Scenario[] = [
  // Acceptance check 4, disabled side: the build flag is the only switch —
  // "false" and a Vite build without the var at all must behave identically.
  { name: "disabled-false", env: { VITE_RUM_ENABLED: "false" } },
  { name: "env-undefined", env: {} },
  // Sampling happens once per page load; 0 is the deterministic sampled-out rate.
  {
    name: "sampled-out",
    env: { ...ENABLED_BASE, VITE_RUM_SAMPLE_RATE: "0" },
  },
  // The collector rejects this build's batches with 500.
  { name: "breaker", env: { ...ENABLED_BASE, VITE_RUM_BUILD_ID: "breaker" } },
  { name: "bounded", env: { ...ENABLED_BASE, VITE_RUM_BUILD_ID: "bounded" } },
  // Firefox-shaped environment: no LCP observer support.
  {
    name: "no-observer",
    env: { ...ENABLED_BASE, VITE_RUM_BUILD_ID: "no-observer" },
    initScript: "window.PerformanceObserver = undefined;",
  },
];

const REJECT_BUILD_ID = "breaker";
const scenarioByName = (name: string): Scenario => {
  const found = scenarios.find((s) => s.name === name);
  if (!found) throw new Error(`unknown scenario ${name}`);
  return found;
};

let server: Server;
let harnessUrl: string;
let workDir: string;
/** Every batch the harness collector accepted or rejected, in order. */
let batches: RumEnvelope[];
/** One entry per POST the collector saw (accepted and rejected). */
let postCount = 0;

function startHarness(): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    server = createServer(async (request, response) => {
      const url = request.url || "/";
      const path = url.split("?")[0];

      if (request.method === "POST" && path === COLLECT_PATH) {
        const chunks: Buffer[] = [];
        for await (const chunk of request) chunks.push(chunk as Buffer);
        postCount += 1;
        let envelope: RumEnvelope | null = null;
        try {
          envelope = JSON.parse(Buffer.concat(chunks).toString("utf8")) as RumEnvelope;
        } catch {
          envelope = null;
        }
        if (envelope) batches.push(envelope);
        // The breaker build is the one that gets rejected; every other
        // scenario gets 202 Accepted-and-discarded, the collector's real
        // disabled answer (test_rum_routes.py pins the server side).
        const refuse = envelope?.build_id === REJECT_BUILD_ID;
        response.writeHead(refuse ? 500 : 202, { "content-type": "application/json" });
        response.end(JSON.stringify({ ok: !refuse }));
        return;
      }

      const scenarioMatch = /^\/([a-z0-9-]+)(?:\/index\.html|\/bundle\.js)$/.exec(path);
      if (request.method === "GET" && scenarioMatch) {
        const [, name] = scenarioMatch;
        if (path.endsWith(".js")) {
          const code = await readFile(join(workDir, `${name}.js`), "utf8");
          response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
          response.end(code);
        } else {
          response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
          response.end(
            `<!doctype html><html><head><meta charset="utf-8"><title>${name}</title></head>` +
              `<body><div id="alive">scenario ${name}</div>` +
              `<script type="module" src="/${name}/bundle.js"></script></body></html>`,
          );
        }
        return;
      }

      response.writeHead(404, { "content-type": "text/plain" });
      response.end("not found");
    });
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
}

/** The page-side driver the bundle exposes over the shipped module's exports. */
interface RumDriver {
  api(fields: {
    method: string;
    path: string;
    status: number;
    outcome: string;
    durationMs: number;
    rawRequestId: string | null;
  }): void;
  pending(): number;
}

async function loadScenario(
  browser: Browser,
  scenario: Scenario,
): Promise<{ context: BrowserContext; page: import("@playwright/test").Page; pageErrors: Error[] }> {
  const context = await browser.newContext();
  if (scenario.initScript) await context.addInitScript(scenario.initScript);
  const page = await context.newPage();
  const pageErrors: Error[] = [];
  page.on("pageerror", (error) => pageErrors.push(error));
  await page.goto(`${harnessUrl}/${scenario.name}/index.html`, { waitUntil: "load" });
  // navigationLoadMs() reads loadEventEnd, which settles just after `load`;
  // give it a beat so the first flush's load-metric behavior is deterministic.
  await page.waitForTimeout(300);
  return { context, page, pageErrors };
}

/** Drive `count` valid shared-client report calls through the real exports. */
async function drive(page: import("@playwright/test").Page, count: number): Promise<void> {
  await page.evaluate(
    ({ n, rawId }) => {
      const driver = (window as unknown as { __rumDriver: RumDriver }).__rumDriver;
      for (let i = 0; i < n; i += 1) {
        driver.api({
          method: "GET",
          path: `/v1/agents/${rawId}?limit=50`,
          status: 200,
          outcome: "ok",
          durationMs: 12.5,
          rawRequestId: null,
        });
      }
    },
    { n: count, rawId: RAW_AGENT_ID },
  );
}

async function dispatchPagehide(page: import("@playwright/test").Page): Promise<void> {
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  workDir = await mkdtemp(join(tmpdir(), "maistro-rum-off-"));
  for (const scenario of scenarios) {
    const entry = join(workDir, `${scenario.name}-entry.ts`);
    await writeFile(
      entry,
      `import { initRum, rumApiRequest, rumPendingForTests } from ${JSON.stringify(
        `${SRC_ROOT}/frontend/src/lib/rum`,
      )};

const driver = { initRum, api: rumApiRequest, pending: rumPendingForTests };
(window as unknown as { __rumDriver: typeof driver }).__rumDriver = driver;
// main.tsx calls this unconditionally on every page load; the module itself
// decides whether collection is on.
initRum();
`,
      "utf8",
    );
    await build({
      entryPoints: [entry],
      outfile: join(workDir, `${scenario.name}.js`),
      bundle: true,
      platform: "browser",
      format: "esm",
      define:
        Object.keys(scenario.env).length > 0
          ? { "import.meta.env": JSON.stringify(scenario.env) }
          : {},
      nodePaths: NODE_PATHS,
      logLevel: "silent",
    });
  }
  batches = [];
  postCount = 0;
  await startHarness();
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("RUM off-switch harness did not bind a TCP port");
  }
  harnessUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  server.close();
  await rm(workDir, { recursive: true, force: true });
});

test("a build without collection enabled never constructs a reporter or sends", async ({
  browser,
}) => {
  for (const scenario of [scenarioByName("disabled-false"), scenarioByName("env-undefined")]) {
    const base = { batches: batches.length, posts: postCount };
    const { context, page, pageErrors } = await loadScenario(browser, scenario);
    // The shared client reports every request through the real hook; with the
    // reporter off, the hook must be a no-op: nothing buffered, nothing sent,
    // even when the pagehide flush boundary fires.
    await drive(page, 5);
    expect(await page.evaluate(() => (window as unknown as { __rumDriver: RumDriver }).__rumDriver.pending())).toBe(0);
    await dispatchPagehide(page);
    await page.waitForTimeout(400);
    expect(await page.evaluate(() => (window as unknown as { __rumDriver: RumDriver }).__rumDriver.pending())).toBe(0);
    expect({ batches: batches.length, posts: postCount }).toEqual(base);
    expect(pageErrors, `${scenario.name}: the reporter must initialize without throwing`).toEqual([]);
    await context.close();
  }
});

test("a sampled-out session (VITE_RUM_SAMPLE_RATE=0) sends nothing", async ({ browser }) => {
  const base = { batches: batches.length, posts: postCount };
  const { context, page, pageErrors } = await loadScenario(browser, scenarioByName("sampled-out"));
  // Sampling is decided once per page load inside initRum, so these events
  // are reported into a session that must never grow a reporter.
  await drive(page, 5);
  expect(await page.evaluate(() => (window as unknown as { __rumDriver: RumDriver }).__rumDriver.pending())).toBe(0);
  await dispatchPagehide(page);
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => (window as unknown as { __rumDriver: RumDriver }).__rumDriver.pending())).toBe(0);
  expect({ batches: batches.length, posts: postCount }).toEqual(base);
  expect(pageErrors).toEqual([]);
  await context.close();
});

test("three consecutive rejected sends trip the breaker: dropped, never retried, then silent", async ({
  browser,
}) => {
  // Tests share one harness collector, so every count below is relative to
  // what earlier scenarios already posted.
  const basePosts = postCount;
  const baseBatches = batches.length;
  const { context, page, pageErrors } = await loadScenario(browser, scenarioByName("breaker"));
  const pending = () =>
    page.evaluate(() => (window as unknown as { __rumDriver: RumDriver }).__rumDriver.pending());

  // Three batch-full flushes, each answered 500. A failed batch is spliced
  // out of the buffer before the send, so between flushes nothing may be
  // re-attempted: the POST count may only move when this test pushes again.
  for (let round = 1; round <= 3; round += 1) {
    await drive(page, MAX_BATCH_EVENTS);
    await expect
      .poll(() => postCount, { message: `flush ${round} should reach the collector exactly once` })
      .toBe(basePosts + round);
    // A dropped batch is gone, not parked: at most the one api event that a
    // concurrent load-metric unshift displaced from the spliced batch.
    expect(await pending(), `after flush ${round}`).toBeLessThanOrEqual(1);
    const stable = { batches: batches.length, posts: postCount };
    await page.waitForTimeout(400);
    expect({ batches: batches.length, posts: postCount }, `no retry after flush ${round}`).toEqual(
      stable,
    );
  }

  // The third consecutive failure disables the reporter for the session:
  // 25 more events must not produce a fourth POST, and the pagehide
  // boundary must stay silent too (no beacon from a disabled reporter).
  await drive(page, MAX_BATCH_EVENTS);
  await dispatchPagehide(page);
  await page.waitForTimeout(500);
  expect(postCount, "a tripped breaker never sends again").toBe(basePosts + 3);
  expect(batches.length).toBe(baseBatches + 3);
  // Rendering must have survived the whole breaker ladder.
  expect(pageErrors).toEqual([]);
  await expect(page.locator("#alive")).toBeVisible();
  await context.close();
});

test("the buffer is bounded: the batch cap ships exactly MAX_BATCH_EVENTS and the rest stay pending", async ({
  browser,
}) => {
  const batchesBeforeThisTest = batches.length;
  const { context, page, pageErrors } = await loadScenario(browser, scenarioByName("bounded"));
  await drive(page, MAX_BATCH_EVENTS + 5);
  await expect
    .poll(() => batches.length, { message: "the full batch should ship" })
    .toBe(batchesBeforeThisTest + 1);
  const shipped = batches[batches.length - 1];
  const loadShipped = shipped.events.some((event) => event.type === "web_vital");
  expect(shipped.events.length, "a batch never exceeds the cap").toBe(MAX_BATCH_EVENTS);
  // Conservation: 30 api events (+ the one load metric, if the navigation had
  // finalized) minus the shipped batch is exactly what remains pending.
  const pending = await page.evaluate(
    () => (window as unknown as { __rumDriver: RumDriver }).__rumDriver.pending(),
  );
  expect(pending).toBe(MAX_BATCH_EVENTS + 5 + (loadShipped ? 1 : 0) - shipped.events.length);
  // And the raw identifiers feeding those events never left the browser.
  const wire = JSON.stringify(shipped);
  expect(wire).not.toContain(RAW_AGENT_ID);
  expect(wire).not.toContain("limit=50");
  expect(pageErrors).toEqual([]);
  await context.close();
});

test("without PerformanceObserver the reporter still initializes and ships the load fallback", async ({
  browser,
}) => {
  const batchesBeforeThisTest = batches.length;
  const { context, page, pageErrors } = await loadScenario(browser, scenarioByName("no-observer"));
  await drive(page, MAX_BATCH_EVENTS);
  await expect.poll(() => batches.length).toBe(batchesBeforeThisTest + 1);
  const shipped = batches[batches.length - 1];
  // The documented fallback: where LCP is unsupported, the finalized `load`
  // navigation timing still leaves the browser — and no LCP ever appears.
  const load = shipped.events.find((event) => event.type === "web_vital" && event.name === "load");
  expect(load, "the load fallback metric must ship").toBeTruthy();
  expect(Number.isFinite(load?.value_ms)).toBe(true);
  expect(load?.value_ms).toBeGreaterThanOrEqual(0);
  expect(shipped.events.some((event) => event.type === "web_vital" && event.name === "LCP")).toBe(
    false,
  );
  expect(pageErrors, "an unsupported API must be a silent degradation").toEqual([]);
  await context.close();
});
