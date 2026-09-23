/**
 * The DAG Builder's Run button reports the canonical Run truthfully (#53).
 *
 * The run socket (`routes/ws.py` over `services/graph_runner.py`) projects one
 * canonical Run: every `node_complete` and terminal frame carries its
 * `run_id`, and the terminal frame's `status` is the canonical Run status --
 * `completed`, `failed`, `cancelled`, `timed_out`, or a parked `waiting` /
 * `paused`. The page used to know only completed/failed, so a parked or
 * cancelled Run read as "Connection closed" and its id was never shown.
 *
 * The socket is intercepted and fed the exact frame shapes the backend emits;
 * the Workspace list and the DAG are stubbed so no execution or Workspace
 * state is created on the shared test instance.
 */

import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

const WORKSPACE_ID = "ws-run-truth";
const DAG_ID = "dag-run-truth";
const RUN_ID = "run-7f3c2a91";
const NODE_ID = "node-alpha-0001";

const dag = {
  id: DAG_ID,
  name: "Run truth DAG",
  description: "",
  nodes: [
    { id: NODE_ID, role: "worker", name: "alpha", agent_id: null, model: null, strategy: "direct", prompt: null, config: {} },
  ],
  edges: [],
  entry_node: NODE_ID,
  max_cycles: 3,
  run_scout: false,
  status: "active",
  created_at: "2026-09-23T00:00:00Z",
  updated_at: "2026-09-23T00:00:00Z",
};

const workspaces = [
  {
    id: WORKSPACE_ID,
    persona_template_id: "pm_fleet",
    name: "Run truth",
    theme_id: "default",
    voice_tone_override: null,
    members: [],
    tool_bindings: [],
    active: true,
  },
];

const started = { status: "started", node_count: 1, entry: NODE_ID };

function nodeComplete(success: boolean) {
  return { status: "node_complete", node_id: NODE_ID, role: "worker", response: "", success, run_id: RUN_ID };
}

let frames: object[] = [];
let socketUrls: string[] = [];

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);

  await page.route(/\/v1\/workspaces(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(workspaces) });
  });
  await page.route(/\/v1\/dags(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([dag]) });
  });
  await page.route(new RegExp(`/v1/dags/${DAG_ID}$`), async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(dag) });
  });
  await page.routeWebSocket(/\/v1\/ws\/dags\/[^/]+\/run/, (ws) => {
    socketUrls.push(ws.url());
    for (const frame of frames) ws.send(JSON.stringify(frame));
    ws.close();
  });
});

test.afterAll(async () => {
  await context.close();
});

async function runWith(sequence: object[]) {
  frames = sequence;
  socketUrls = [];
  await page.goto("/dags", { waitUntil: "domcontentloaded" });
  await page.getByText(dag.name, { exact: true }).first().click();
  await page.getByRole("button", { name: /Run DAG/ }).click();
  const log = page.getByRole("log", { name: "DAG execution log" });
  await expect(log).toBeVisible();
  // The run button re-enables once the page stops treating the Run as live.
  await expect(page.getByRole("button", { name: /Run DAG/ })).toBeEnabled();
  expect(socketUrls).toHaveLength(1);
  expect(new URL(socketUrls[0]).searchParams.get("workspace_id")).toBe(WORKSPACE_ID);
  return log;
}

async function expectRunLink(log: ReturnType<Page["getByRole"]>) {
  await expect(log).toContainText(`Run ${RUN_ID}`);
  const link = log.getByRole("link", { name: /DAG Runs/ });
  await expect(link).toHaveAttribute("href", `/dag-runs?run=${RUN_ID}`);
}

test("a completed Run shows its canonical id and Completed", async () => {
  const log = await runWith([started, nodeComplete(true), { status: "completed", run_id: RUN_ID, cycles: 1, annotations: {} }]);
  await expect(log).toContainText(`worker (${NODE_ID.slice(0, 8)}): OK`);
  await expect(log).toContainText("Completed in 1 cycles");
  await expectRunLink(log);
  await expect(log).not.toContainText("Connection closed");
  await expect(page.getByText("DAG execution completed")).toBeVisible();
});

test("a parked (waiting) Run is shown as parked with its id, not success or a dropped connection", async () => {
  const log = await runWith([started, { status: "waiting", run_id: RUN_ID, error: "canonical Run ended waiting" }]);
  await expect(log).toContainText("Parked (waiting)");
  await expectRunLink(log);
  await expect(log).not.toContainText("Connection closed");
  await expect(log).not.toContainText("Completed");
  await expect(log).not.toContainText("Failed");
  await expect(page.getByText("DAG execution completed")).toHaveCount(0);
});

test("a paused Run is shown as parked, not finished", async () => {
  const log = await runWith([started, nodeComplete(true), { status: "paused", run_id: RUN_ID, error: "canonical Run ended paused" }]);
  await expect(log).toContainText("Parked (paused)");
  await expectRunLink(log);
  await expect(log).not.toContainText("Connection closed");
  await expect(page.getByText("DAG execution completed")).toHaveCount(0);
});

test("a cancelled Run is a non-success terminal state", async () => {
  const log = await runWith([started, nodeComplete(false), { status: "cancelled", run_id: RUN_ID, error: "cancelled by operator" }]);
  await expect(log).toContainText("Cancelled: cancelled by operator");
  await expectRunLink(log);
  await expect(log).not.toContainText("Completed");
  await expect(log).not.toContainText("Connection closed");
  await expect(page.getByText("DAG execution completed")).toHaveCount(0);
  await expect(page.getByText("DAG run cancelled")).toBeVisible();
});

test("a timed-out Run is a non-success terminal state", async () => {
  const log = await runWith([started, { status: "timed_out", run_id: RUN_ID, error: "deadline exceeded" }]);
  await expect(log).toContainText("Timed out: deadline exceeded");
  await expectRunLink(log);
  await expect(log).not.toContainText("Connection closed");
  await expect(page.getByText("DAG execution completed")).toHaveCount(0);
});

test("a failed node and failed Run read FAIL and Failed", async () => {
  const log = await runWith([started, nodeComplete(false), { status: "failed", run_id: RUN_ID, error: "node alpha failed" }]);
  await expect(log).toContainText(`worker (${NODE_ID.slice(0, 8)}): FAIL`);
  await expect(log).toContainText("Failed: node alpha failed");
  await expectRunLink(log);
  await expect(log).not.toContainText("Connection closed");
  await expect(page.getByText("DAG execution completed")).toHaveCount(0);
});

test("a socket that closes before any terminal frame still says the connection closed", async () => {
  const log = await runWith([started, nodeComplete(true)]);
  await expect(log).toContainText("Connection closed before the Run reported a final state");
  await expect(log).not.toContainText("Completed");
});
