/**
 * The DAG Builder closes its Run socket and strips its handlers on unmount (#355).
 *
 * `handleRun` opens `/v1/ws/dags/{id}/run` from a click handler, not an
 * effect, so nothing used to tie that socket to the component's life:
 * navigating during a Run left the connection — and its live
 * `setExecState`/`toast` handlers — pointed at an unmounted tree.
 *
 * The socket's one safe close point is the backend's `started` frame:
 * `execute_dag_streaming` is an async generator that yields `started` BEFORE
 * awaiting `execute_dag`, so the durable Run (and its projection) only exists
 * once the consumer resumes past that frame. Closing a CONNECTING socket or
 * racing the ack would cancel a Run the user explicitly requested. Unmount
 * therefore detaches immediately once the Run is acknowledged or settled, and
 * before that only arms a `detach` flag the frame handlers act on at the safe
 * point. This spec repeatedly mounts and unmounts the page while a Run stream
 * is pre-acknowledgement (connected, `started` not yet delivered),
 * acknowledged-and-running (past `started`, no terminal frame),
 * settled-failed (terminal `failed` frame delivered, backend closed), and
 * unsettled-then-resumed, and asserts:
 *   - an unmount before the ack does NOT close yet (that would cancel the
 *     Run); the moment the backend's `started` frame arrives, the page CLOSES
 *     the socket and has NULLED its handlers — no leaked connection or
 *     listener survives navigation;
 *   - an unmount after the ack closes the socket from the page immediately,
 *     handlers stripped; a Run that already settled server-side leaves nothing
 *     to close and no re-subscription;
 *   - the page SENDS nothing over the socket on the way out. The protocol has
 *     no client-side cancel message, so a remount resumes from canonical state
 *     (DAG Runs), not a dead socket;
 *   - no uncaught page errors fire around the unmount;
 *   - a remount refetches canonical state and a fresh Run opens exactly one
 *     new socket — subscriptions never stack.
 *
 * `window.WebSocket` is replaced by an instrumented fake for the whole spec:
 * the Run socket is the only WebSocket the SPA ever opens, the fake records
 * `close()` calls, the handler references present at close time, and every
 * `send()` the page makes, while frames are driven from the test via
 * `serverSend`/`serverClose`. (Playwright's `routeWebSocket` was tried first
 * and works for full page loads, but its interception silently misses sockets
 * a client-side-routed page opens, which this spec's unmount assertions need.)
 * Workspaces and the DAG list/detail are stubbed at the HTTP layer the same
 * way `dag-run-button-truthfulness.spec.ts` does, so no execution or
 * Workspace state is created on the shared test instance.
 */

import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

const WORKSPACE_ID = "ws-unmount";
const DAG_ID = "dag-unmount";
const RUN_ID = "run-unmount-0001";
const NODE_ID = "node-unmount-001";

const dag = {
  id: DAG_ID,
  name: "Unmount cleanup DAG",
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
    name: "Unmount cleanup",
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

type SocketSnapshot = {
  url: string;
  closeCalled: boolean;
  closeCode: number | null;
  // Handler references still attached when close() ran: the fix strips them
  // (all null) before closing; a leaked socket keeps them live.
  handlersAtClose: { onmessage: unknown; onerror: unknown; onclose: unknown } | null;
  // Frames the page SENT to the server. There is no client-cancel message in
  // this protocol, so this stays empty across a mid-Run unmount.
  sent: string[];
};

/** Read a fake-socket record from the page and drop non-serializable fields. */
async function socketSnapshots(): Promise<SocketSnapshot[]> {
  return page.evaluate(() =>
    (window as unknown as { __runSockets: Array<Record<string, unknown>> }).__runSockets.map((s) => ({
      url: s.url as string,
      closeCalled: s.closeCalled as boolean,
      closeCode: s.closeCode as number | null,
      handlersAtClose: s.handlersAtClose as SocketSnapshot["handlersAtClose"],
      sent: s.sent as string[],
    })),
  );
}

/** The fix nulls all three handlers before closing; a leaked one stays live. */
function expectHandlersStripped(s: SocketSnapshot): void {
  expect(s.handlersAtClose, "handlers at close time").toEqual({ onmessage: null, onerror: null, onclose: null });
}

/** Drive frames into the page as if the backend had sent them. */
async function serverSend(socketIndex: number, frame: object) {
  await page.evaluate(([i, f]) => {
    const sock = (window as unknown as { __runSockets: Array<{ serverSend: (f: object) => void }> }).__runSockets[i as number];
    sock.serverSend(f as object);
  }, [socketIndex, frame] as const);
}

/** Simulate the backend closing the (still server-open) socket. */
async function serverClose(socketIndex: number) {
  await page.evaluate((i) => {
    const sock = (window as unknown as { __runSockets: Array<{ serverClose: () => void }> }).__runSockets[i];
    sock.serverClose();
  }, socketIndex);
}

let pageErrors: string[] = [];
let consoleErrors: string[] = [];
let dagListFetches = 0;
let dagDetailFetches = 0;

async function resetRunSockets() {
  // Truncate IN PLACE: the FakeWebSocket class in the init script closes over
  // the array it captured at document start — replacing window.__runSockets
  // here would orphan that array and every later push would be invisible.
  await page.evaluate(() => { (window as unknown as { __runSockets: unknown[] }).__runSockets.splice(0); });
  pageErrors = [];
  consoleErrors = [];
}

async function expectNoErrors() {
  expect(pageErrors, "uncaught page exceptions").toEqual([]);
  // The app's CSP refuses an inline data: font on this page — pre-existing at
  // the base head and unrelated to socket lifecycle; everything else must be
  // silent (a leaked handler would surface here as a React/JS error).
  const relevant = consoleErrors.filter((e) => !e.includes("Content Security Policy directive"));
  expect(relevant, "console errors (minus the pre-existing CSP font refusal)").toEqual([]);
}

/** Mount the builder via SPA navigation, select the DAG, start a Run. */
async function mountAndRun() {
  await page.getByRole("link", { name: "DAG Builder", exact: true }).click();
  await page.getByText(dag.name, { exact: true }).first().click();
  // Precondition: the stubbed workspace is active, or Run would refuse.
  await expect(page.getByRole("tab", { name: workspaces[0].name })).toBeVisible();
  const runButton = page.getByRole("button", { name: /Run DAG/ });
  await expect(runButton).toBeEnabled();
  await runButton.click();
  const log = page.getByRole("log", { name: "DAG execution log" });
  await expect(log).toBeVisible();
  await expect(log).toContainText("Connecting...");
  const sockets = await socketSnapshots();
  expect(sockets, "one Run socket per Run click").toHaveLength(1);
  expect(sockets[0].url).toContain(`/v1/ws/dags/${DAG_ID}/run`);
  expect(sockets[0].url).toContain(`workspace_id=${WORKSPACE_ID}`);
  return log;
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
    // Instrumented stand-in for the Run socket. Records lifecycle facts the
    // assertions need: close() calls (and who was attached at that moment),
    // everything the page sends, plus serverSend/serverClose for the test to
    // play the backend with.
    const sockets: Array<Record<string, unknown>> = [];
    (window as unknown as { __runSockets: Array<Record<string, unknown>> }).__runSockets = sockets;
    class FakeWebSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      CONNECTING = 0;
      OPEN = 1;
      CLOSING = 2;
      CLOSED = 3;
      url: string;
      readyState = 0;
      sent: string[] = [];
      onopen: unknown = null;
      onmessage: unknown = null;
      onerror: unknown = null;
      onclose: unknown = null;
      closeCalled = false;
      closeCode: number | null = null;
      handlersAtClose: Record<string, unknown> | null = null;
      constructor(url: string | URL) {
        this.url = String(url);
        sockets.push(this);
        queueMicrotask(() => {
          this.readyState = 1;
          if (typeof this.onopen === "function") (this.onopen as (ev: unknown) => void)({});
        });
      }
      send(data: string) {
        this.sent.push(String(data));
      }
      close(code = 1000) {
        if (this.closeCalled) return;
        this.closeCalled = true;
        this.closeCode = code;
        this.handlersAtClose = { onmessage: this.onmessage, onerror: this.onerror, onclose: this.onclose };
        this.readyState = 3;
        if (typeof this.onclose === "function") (this.onclose as (ev: unknown) => void)({ code });
      }
      serverSend(frame: object) {
        if (this.readyState !== 3 && typeof this.onmessage === "function") {
          (this.onmessage as (ev: unknown) => void)({ data: JSON.stringify(frame) });
        }
      }
      serverClose() {
        if (this.readyState !== 3) {
          this.readyState = 3;
          if (typeof this.onclose === "function") (this.onclose as (ev: unknown) => void)({ code: 1000 });
        }
      }
    }
    (window as unknown as { WebSocket: unknown }).WebSocket = FakeWebSocket;
  });
  page = await context.newPage();
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (req.method() === "GET" && url.pathname === "/v1/dags") dagListFetches += 1;
    if (req.method() === "GET" && url.pathname === `/v1/dags/${DAG_ID}`) dagDetailFetches += 1;
  });

  // HTTP stubs are registered BEFORE the session helpers run: this spec never
  // full-reloads after login (every unmount under test is an SPA navigation,
  // not a goto), so the app's one and only workspace fetch happens on the
  // post-login mount and must already be intercepted here.
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
  // The page's other lifecycle fetches; answered so they cannot error.
  await page.route(/\/v1\/agents(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/v1\/settings\/models(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ models: ["test-model"] }) });
  });

  await setupIfNeeded(page);
  await loginAsPM(page);
});

test.afterAll(async () => {
  await context.close();
});

test("unmounting before the Run is acknowledged defers the close to the `started` safe point", async () => {
  await resetRunSockets();
  await mountAndRun();
  // Still live and NOT yet acknowledged: no frame has been delivered, so the
  // backend generator has not resumed past `started` and `execute_dag` has not
  // run. Closing now could cancel a Run the user explicitly requested.
  await expect(page.getByRole("button", { name: /Running/ })).toBeDisabled();

  // SPA navigation mid-Run unmounts the page. Cleanup arms `detach` instead of
  // closing: the socket must still be open here.
  await page.getByRole("link", { name: "DAG Runs", exact: true }).click();
  await expect(page).toHaveURL(/\/dag-runs$/);
  expect((await socketSnapshots())[0].closeCalled, "no close before the ack — it would cancel the requested Run").toBe(false);

  // The backend's `started` frame is the safe point: the Run now exists
  // server-side regardless of this socket, so the armed cleanup detaches —
  // handlers stripped, socket closed, nothing sent, nothing state-updated.
  await serverSend(0, started);
  await expect.poll(async () => (await socketSnapshots())[0].closeCalled, "the page closed the run socket at the safe point").toBe(true);
  const sockets = await socketSnapshots();
  expectHandlersStripped(sockets[0]);
  expect(sockets[0].sent, "navigation must not send anything — no client-cancel exists in the protocol").toEqual([]);
  await expectNoErrors();
});

test("unmounting during an acknowledged, still-running Run closes the socket from the page immediately", async () => {
  await resetRunSockets();
  const log = await mountAndRun();
  // Acknowledge the Run while mounted: past `started`, `execute_dag` is
  // running server-side and this socket is dispensable.
  await serverSend(0, started);
  await serverSend(0, nodeComplete(true));
  await expect(log).toContainText("Started (1 nodes)");

  await page.getByRole("link", { name: "DAG Runs", exact: true }).click();
  await expect(page).toHaveURL(/\/dag-runs$/);
  await expect.poll(async () => (await socketSnapshots())[0].closeCalled, "the page closed the acknowledged run socket on unmount").toBe(true);
  const sockets = await socketSnapshots();
  expectHandlersStripped(sockets[0]);
  expect(sockets[0].sent).toEqual([]);
  await expectNoErrors();
});

test("unmounting after a settled failed Run leaks no connection and logs no errors", async () => {
  await resetRunSockets();
  const log = await mountAndRun();
  const finished = [started, nodeComplete(false), { status: "failed", run_id: RUN_ID, error: "node alpha failed" }];
  for (const frame of finished) await serverSend(0, frame);
  await serverClose(0); // the backend closes after a terminal frame
  await expect(log).toContainText("Failed: node alpha failed");
  await expect(page.getByRole("button", { name: /Run DAG/ })).toBeEnabled();

  await page.getByRole("link", { name: "DAG Runs", exact: true }).click();
  await expect(page).toHaveURL(/\/dag-runs$/);

  const sockets = await socketSnapshots();
  expect(sockets, "a settled Run must not have re-subscribed").toHaveLength(1);
  expect(sockets[0].sent).toEqual([]);
  await expectNoErrors();
});

test("a remount after leaving mid-Run resumes from canonical state with exactly one new subscription", async () => {
  await resetRunSockets();
  await mountAndRun(); // leave a Run in flight again

  await page.getByRole("link", { name: "DAG Runs", exact: true }).click();
  await expect(page).toHaveURL(/\/dag-runs$/);
  // The unmount armed `detach` (the Run was never acknowledged); the backend
  // keeps executing and sends `started` to the still-open socket, where the
  // armed cleanup finally closes it.
  expect((await socketSnapshots())[0].closeCalled, "still open before the ack").toBe(false);
  await serverSend(0, started);
  await expect.poll(async () => (await socketSnapshots())[0].closeCalled).toBe(true);
  expectHandlersStripped((await socketSnapshots())[0]);

  // Remount: canonical state is refetched, not resumed from dead component
  // state — the run button is idle, not stuck "Running...".
  const listFetchesBefore = dagListFetches;
  const detailFetchesBefore = dagDetailFetches;
  await page.getByRole("link", { name: "DAG Builder", exact: true }).click();
  await page.getByText(dag.name, { exact: true }).first().click();
  const runButton = page.getByRole("button", { name: /Run DAG/ });
  await expect(runButton).toBeEnabled();
  expect(dagListFetches).toBeGreaterThan(listFetchesBefore);
  expect(dagDetailFetches).toBeGreaterThan(detailFetchesBefore);

  // Exactly one NEW socket for the new Run — no duplicate subscription to the
  // old, closed one.
  await runButton.click();
  await expect(page.getByRole("log", { name: "DAG execution log" })).toContainText("Connecting...");
  const sockets = await socketSnapshots();
  expect(sockets, "one fresh subscription, no duplicates").toHaveLength(2);
  expect(sockets[0].closeCalled, "the first socket is still closed").toBe(true);
  expect(sockets[1].sent).toEqual([]);

  // The new subscription is live and functional: deliver the terminal frame
  // the backend would send and the fresh mount reports the completed Run.
  await serverSend(1, { status: "completed", run_id: RUN_ID, cycles: 1, annotations: {} });
  await expect(page.getByRole("log", { name: "DAG execution log" })).toContainText("Completed in 1 cycles");
  await expectNoErrors();
});
