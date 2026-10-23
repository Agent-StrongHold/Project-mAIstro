/**
 * RSI polling survives a hostile backend without unhandled rejections (#359).
 *
 * The RSI page used to run two bare `setInterval` + `Promise.all` loops (the
 * dashboard refresh and the selected run's patch feed) with no catch, no
 * backoff, no cancellation, and no visibility check: one backend interruption
 * produced an unhandled rejection every tick, forever, at a fixed cadence,
 * and an in-flight request outlived the page. This spec drives the page
 * through every failure shape the loop must survive and asserts the fix's
 * contract:
 *
 *   - states are DISTINCT: unreachable (transport), server-error (5xx),
 *     unauthorized (401/403), empty (healthy, zero rows), and — only from a
 *     real status body — "not installed"; no answer at all renders as
 *     "status unknown", never as a fact about the installation;
 *   - an intermittent outage keeps the last known data on screen and the
 *     banner clears on recovery (no unhandled page errors — the point of the
 *     fix);
 *   - a prolonged outage backs off exponentially with jitter and is BOUNDED:
 *     under page.clock each failed poll's gap doubles (interval * 2^failures,
 *     75% jitter) until the 60s cap floors the cadence — a five-virtual-minute
 *     outage costs ~7 requests where the old fixed 5s interval would have
 *     fired ~60;
 *   - the first success resets the cadence to the base interval;
 *   - the loop pauses while the tab is hidden and while the browser is
 *     offline, and re-kicks immediately on visibilitychange / online;
 *   - an unmount aborts the in-flight request (the fetch rejects as
 *     AbortError) and stops the loop dead — no request fires afterwards;
 *   - a slow response never overlaps the next poll: the next request is
 *     scheduled only after the slow one settles.
 *
 * Everything under /v1 is intercepted (auth, setup, workspaces, RSI), so the
 * journeys depend on no instance credential and no RSI worker — the same
 * hermetic style as dag-builder-unmount-cleanup.spec.ts. The page is served
 * as a production build (vite preview): React StrictMode's dev-only effect
 * double-invoke would double every request count below.
 *
 * Determinism: Math.random is pinned to 0.5 via an init script, so the hook's
 * 50–100% jitter always lands on 75% of the computed delay — steady cadence
 * is exactly 3.75s (dashboard) / 3.0s (patch feed), first backoff step
 * exactly 7.5s, and the clock-driven test can assert exact gaps.
 *
 * Run book (from packages/hive-conductor):
 *   cd frontend && npm run build
 *   npx vite preview --port 8199 &
 *   cd ../tests/e2e && HIVE_BASE_URL=http://localhost:8199 \
 *     npx playwright test rsi-polling-resilience.spec.ts
 */

import { expect, test, type BrowserContext, type Page, type Route } from "@playwright/test";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

type Mode = "ok" | "abort" | "server-error" | "unauthorized";

const RUN_ID = "run-ui-a";
const RUN = {
  run_id: RUN_ID,
  mode: "cleanup",
  status: "completed",
  started_at: "2026-01-01T00:00:00Z",
  ended_at: null,
  cycles: 5,
  promotions: 2,
  last_error: null,
  summary: null,
  config: {},
  report_dir: null,
};

/** Every endpoint's failure mode plus the data it serves when "ok". Flipped
 * live by the tests; read by the route handlers registered once below. */
const ctl = {
  statusMode: "ok" as Mode,
  runsMode: "ok" as Mode,
  modelsMode: "ok" as Mode,
  profilesMode: "ok" as Mode,
  reviewsMode: "ok" as Mode,
  rlphdMode: "ok" as Mode,
  available: true,
  runs: [RUN] as Array<Record<string, unknown>>,
  reviewsDelayMs: 0,
};
const counts = { status: 0, runs: 0, models: 0, profiles: 0, reviews: 0, rlphd: 0 };
const times = { status: [] as number[], reviews: [] as number[] };

function setModes(mode: Mode): void {
  ctl.statusMode = mode;
  ctl.runsMode = mode;
  ctl.modelsMode = mode;
  ctl.profilesMode = mode;
}

async function respond(route: Route, mode: Mode, payload: () => unknown): Promise<void> {
  if (mode === "abort") return void (await route.abort("connectionreset"));
  if (mode === "server-error") return void (await route.fulfill({ status: 503, json: { detail: "rsi exploded" } }));
  if (mode === "unauthorized") return void (await route.fulfill({ status: 401, json: { detail: "session expired" } }));
  await route.fulfill({ json: payload() });
}

async function slowDelay(route: Route): Promise<void> {
  if (ctl.reviewsDelayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, ctl.reviewsDelayMs));
    // The point of the slow route can be that the page ABORTS it (unmount);
    // fulfilling a disposed route then throws, which is not a defect.
  }
}

let pageErrors: string[] = [];

async function mount(): Promise<void> {
  await page.goto("/rsi", { waitUntil: "domcontentloaded" });
  const refresh = page.getByRole("button", { name: "Refresh" });
  try {
    await refresh.waitFor({ state: "visible", timeout: 8_000 });
  } catch {
    // The app's boot occasionally stalls on a static chunk that never
    // arrives from the preview server (dev-server flake, not the loop under
    // test — every assertion below targets the page AFTER it is up). One
    // reload re-requests the chunk; if the page still does not come up, the
    // failure is real and surfaces here.
    await page.reload({ waitUntil: "domcontentloaded" });
    await refresh.waitFor({ state: "visible", timeout: 15_000 });
  }
}

/** The banner is the four-state surface: its data-health attribute is the
 * machine-readable state, the text is the human one. */
function pollBanner() {
  return page.getByTestId("rsi-poll-health");
}

async function setHidden(hidden: boolean): Promise<void> {
  await page.evaluate((h) => {
    const doc = document as unknown as Record<string, unknown>;
    Object.defineProperty(doc, "hidden", { configurable: true, get: () => h });
    Object.defineProperty(doc, "visibilityState", { configurable: true, get: () => (h ? "hidden" : "visible") });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);
}

async function setOnline(online: boolean): Promise<void> {
  await page.evaluate((on) => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => on });
    window.dispatchEvent(new Event(on ? "online" : "offline"));
  }, online);
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  // Every page in this context reports uncaught exceptions — the whole point
  // of the fix is that a dead backend used to produce them every tick.
  context.on("page", (p) => p.on("pageerror", (err) => pageErrors.push(String(err))));
  await stubPageEnv(context);
  await stubV1Routes(context);

  page = await context.newPage();
});

test.afterAll(async () => {
  // Detach the RSI page and its polling loops (and the 2.5 s patch-feed
  // route delay) from the worker-scoped browser before the next spec runs.
  await context.close();
});

/** Onboarding seed, pinned jitter, and the page-side request journal — the
 * environment every app page in a context needs. The clock test installs
 * these on its own isolated context, because Playwright's clock API
 * registers CONTEXT-level init scripts: reusing this context there would
 * replay its paused clock into every later navigation and wedge the app's
 * boot. */
async function stubPageEnv(scope: BrowserContext): Promise<void> {
  await scope.addInitScript(() => {
    // An opaque origin (about:blank and friends) throws on localStorage
    // access, which would surface as a page error. The seed only matters on
    // the app's own origin.
    try {
      window.localStorage.setItem("hive_onboarded", "1");
    } catch {
      /* opaque origin — nothing to seed */
    }
    // Pin the backoff jitter: 50–100% of the computed delay always lands on
    // 75%, which makes every cadence below an exact number.
    Math.random = () => 0.5;
    // Record fetch START stamps and rejections from INSIDE the page: under
    // the fake clock the page's Date.now() is virtual time, while a Node-side
    // route handler would stamp with the real clock — useless for measuring
    // virtual gaps. Rejections carry the DOMException name, so an abort the
    // APP performed (AbortController on unmount) is visible as AbortError —
    // a request held by a pending route handler emits no Node-side
    // requestfailed event when the page aborts it.
    const w = window as unknown as {
      __rsiStarts: Array<{ url: string; t: number }>;
      __rsiFails: Array<{ url: string; name: string }>;
    };
    w.__rsiStarts = [];
    w.__rsiFails = [];
    const wrapped = window.fetch.bind(window);
    window.fetch = (...args: Parameters<typeof fetch>) => {
      const url = String(args[0]);
      if (url.includes("/v1/rsi/")) w.__rsiStarts.push({ url, t: Date.now() });
      return wrapped(...args).then(
        (res) => res,
        (err: unknown) => {
          if (url.includes("/v1/rsi/")) {
            w.__rsiFails.push({ url, name: (err as { name?: string })?.name ?? "unknown" });
          }
          throw err;
        },
      );
    };
  });
}

/** Every /v1 endpoint stubbed at the context: the journeys depend on no
 * instance credential and no RSI worker. Registered FIRST = consulted LAST
 * (Playwright matches LIFO): the catch-all only answers paths no specific
 * stub below covers, so a stray shell fetch can never hit the real backend.
 * Installable on any context — the clock test uses its own. */
async function stubV1Routes(scope: BrowserContext): Promise<void> {
  await scope.route("**/v1/**", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({ json: {} });
  });
  await scope.route("**/v1/setup/status", (route) => route.fulfill({ json: { setup_complete: true } }));
  await scope.route("**/v1/auth/whoami", (route) =>
    route.fulfill({
      json: {
        authenticated: true,
        user: {
          id: "user-rsi-spec",
          username: "rsi-spec",
          role: "user",
          permissions: [],
          did: null,
          elevated: false,
          elevated_until: null,
        },
      },
    }),
  );
  await scope.route(/\/v1\/workspaces(\?.*)?$/, (route) =>
    route.fulfill({
      json: [
        {
          id: "ws-rsi",
          persona_template_id: "pm_fleet",
          name: "RSI polling spec",
          theme_id: "default",
          voice_tone_override: null,
          members: [],
          tool_bindings: [],
          active: true,
        },
      ],
    }),
  );

  await scope.route("**/v1/rsi/status", (route) => {
    counts.status += 1;
    times.status.push(Date.now());
    return respond(route, ctl.statusMode, () => ({
      available: ctl.available,
      active_runs: ctl.runs.length,
      total_runs: ctl.runs.length,
    }));
  });
  await scope.route("**/v1/rsi/runs", (route) => {
    counts.runs += 1;
    return respond(route, ctl.runsMode, () => ctl.runs);
  });
  await scope.route("**/v1/rsi/models", (route) => {
    counts.models += 1;
    return respond(route, ctl.modelsMode, () => ({ models: [] }));
  });
  await scope.route("**/v1/rsi/test-profiles", (route) => {
    counts.profiles += 1;
    return respond(route, ctl.profilesMode, () => ({ profiles: [{ name: "pytest", argv: ["pytest", "-q"] }] }));
  });
  await scope.route("**/v1/rsi/runs/*/reviews", async (route) => {
    counts.reviews += 1;
    times.reviews.push(Date.now());
    await slowDelay(route);
    try {
      await respond(route, ctl.reviewsMode, () => ({ kept: [], flagged: [] }));
    } catch {
      // Route disposed by the page aborting us — that IS the unmount test.
    }
  });
  await scope.route("**/v1/rsi/runs/*/rlphd", async (route) => {
    counts.rlphd += 1;
    await slowDelay(route);
    try {
      await respond(route, ctl.rlphdMode, () => ({ thetas: { cleanup: 0.5 } }));
    } catch {
      // Same as above: aborted by the page on unmount.
    }
  });
  await scope.route("**/v1/rsi/runs/*/stop", (route) => route.fulfill({ json: { ok: true } }));
}

test.beforeEach(() => {
  setModes("ok");
  ctl.reviewsMode = "ok";
  ctl.rlphdMode = "ok";
  ctl.available = true;
  ctl.runs = [RUN];
  ctl.reviewsDelayMs = 0;
  for (const key of Object.keys(counts) as Array<keyof typeof counts>) counts[key] = 0;
  times.status.splice(0);
  times.reviews.splice(0);
  pageErrors = [];
});

test("unreachable, server-error, unauthorized, empty and not-installed render as five distinct states", async () => {
  // Transport death: the page must say "unreachable" and "status unknown" —
  // never a fake "not installed" fact, never a blank page.
  setModes("abort");
  await mount();
  const banner = pollBanner();
  await expect(banner).toHaveAttribute("data-health", "unreachable", { timeout: 10_000 });
  await expect(page.getByText("RSI status unknown")).toBeVisible();
  await expect(page.getByText("No runs loaded yet — see the poll status above.")).toBeVisible();
  await expect(page.getByText("maistro-rsi not installed")).toHaveCount(0);

  // Recovery through the loop (banner clears without a reload) is covered by
  // the intermittent-outage test below; reloading here with healthy modes
  // shows the healthy strip again.
  setModes("ok");
  ctl.runs = [];
  await mount();
  await expect(page.getByText("No runs yet.")).toBeVisible({ timeout: 10_000 });
  await expect(pollBanner()).toHaveCount(0);

  // 401 is a session problem with its own message.
  ctl.runs = [RUN];
  ctl.runsMode = "unauthorized";
  await mount();
  await expect(pollBanner()).toHaveAttribute("data-health", "unauthorized", { timeout: 10_000 });
  await expect(pollBanner()).toContainText(/sign in/i);

  // 5xx is a server problem, distinct from both. The endpoints that DID
  // answer still land (status says available), and no banner claims the page
  // is empty.
  ctl.runsMode = "server-error";
  await mount();
  await expect(pollBanner()).toHaveAttribute("data-health", "server-error", { timeout: 10_000 });
  await expect(pollBanner()).toContainText(/server errors/i);
  await expect(page.getByText("maistro-rsi available")).toBeVisible();

  // "Not installed" is stated only by a real status body — and it is a fact,
  // not a failure: no error banner.
  setModes("ok");
  ctl.available = false;
  await mount();
  await expect(page.getByText("maistro-rsi not installed")).toBeVisible({ timeout: 10_000 });
  await expect(pollBanner()).toHaveCount(0);
});

test("an intermittent outage keeps the last known runs on screen and clears its banner on recovery", async () => {
  await mount();
  const row = page.getByRole("button", { name: `completed ${RUN_ID} 2/5 promoted` });
  await expect(row).toBeVisible({ timeout: 10_000 });

  setModes("abort");
  await expect(pollBanner()).toHaveAttribute("data-health", "unreachable", { timeout: 10_000 });
  // The outage must not clear the last known state.
  await expect(row).toBeVisible();

  setModes("ok");
  await expect(pollBanner()).toHaveCount(0, { timeout: 12_000 });
  await expect(row).toBeVisible();
  const after = counts.status;
  expect(after, "recovery happened through the loop, not a reload").toBeGreaterThanOrEqual(3);
  // The whole journey is the fix's point: zero unhandled rejections.
  expect(pageErrors, "uncaught page exceptions").toEqual([]);
});

test("a prolonged outage backs off exponentially: exact doubling gaps bounded at the 60s cap", async ({ browser }) => {
  // The fake clock lives on its OWN context: Playwright implements clock
  // APIs as context-level init scripts that replay install/pause/runFor into
  // EVERY document, so running it on the shared context would leave every
  // later navigation booted under a paused clock. Playwright 1.60 has no
  // clock uninstall; an isolated context is the uninstall.
  const clockContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const errors: string[] = [];
  clockContext.on("page", (p) => p.on("pageerror", (err) => errors.push(String(err))));
  await stubPageEnv(clockContext);
  await stubV1Routes(clockContext);
  const cpage = await clockContext.newPage();
  await cpage.clock.install({ time: new Date("2026-01-01T00:00:00Z") });
  // Pause one virtual minute PAST the install instant: between the two calls
  // the fake clock keeps ticking with real time, so pauseAt at the install
  // instant itself can already be "fast-forward to the past".
  await cpage.clock.pauseAt(new Date("2026-01-01T00:01:00Z"));
  try {
    await cpage.goto("/rsi", { waitUntil: "domcontentloaded" });
    // Under the PAUSED clock the app's boot commit itself needs virtual time
    // to move (boot-order detail the loop under test does not care about), so
    // nudge the clock until the page is interactive. Nudges may fire extra
    // healthy polls — they never touch the failure ladder.
    const flushUntilInteractive = async () => {
      await expect
        .poll(
          async () => {
            await cpage.clock.runFor(1_000);
            return (await cpage.getByRole("button", { name: "Refresh" }).count()) > 0;
          },
          { timeout: 12_000, intervals: [50] },
        )
        .toBe(true);
    };
    try {
      await flushUntilInteractive();
    } catch {
      // The same dev-server boot flake mount() absorbs: one reload
      // re-requests the static chunks. The clock replay (context init
      // scripts) applies to the reloaded document too, and the journal read
      // below happens after this, so a reload is invisible to the ladder.
      await cpage.reload({ waitUntil: "domcontentloaded" });
      await flushUntilInteractive();
    }
    const starts = async (): Promise<number[]> =>
      cpage.evaluate(() =>
        (window as unknown as { __rsiStarts: Array<{ url: string; t: number }> }).__rsiStarts
          .filter((r) => r.url.includes("/rsi/status"))
          .map((r) => r.t),
      );
    // Real-time settle (the clock is paused: no timer can fire, only
    // in-flight responses land), so the ladder flip starts from quiet state.
    await new Promise((resolve) => setTimeout(resolve, 400));
    const bootStamps = await starts();
    const n0 = bootStamps.length;

    // ── the outage begins ──
    setModes("abort");
    // Fire the pending steady timer (due within one base interval of the
    // last healthy poll): it fails and increments failures to 1. The chunk
    // deliberately overshoots the fire — Playwright anchors timer deadlines
    // at the CHUNK END, and the failure settles (in real time, clock frozen
    // at that same chunk end) — so the first backoff deadline is exactly
    // flipEnd + delay, which is exactly what the loop's rearm computes:
    // interval * 2^failures * 0.75 (jitter pinned).
    const flipStart = await cpage.evaluate(() => Date.now());
    await cpage.clock.runFor(10_000);
    await new Promise((resolve) => setTimeout(resolve, 200));
    let stamps = await starts();
    expect(stamps.length, "the first outage poll fired").toBe(n0 + 1);
    const flipEnd = flipStart + 10_000;
    await cpage.clock.runFor(7_500);
    await expect
      .poll(async () => {
        await cpage.clock.runFor(5);
        return (await starts()).length;
      }, { intervals: [25], timeout: 15_000 })
      .toBe(n0 + 2);
    stamps = await starts();
    expect(stamps.length, "exactly one poll in the first backoff step").toBe(n0 + 2);
    expect(
      Math.abs(stamps[n0 + 1] - flipEnd - 7_500),
      "first backoff step = interval·2¹ at pinned jitter, from the rearm instant",
    ).toBeLessThanOrEqual(10);

    // Each later step: advance the clock by exactly the expected delay. The
    // timer fires AT its deadline (stamp = deadline); its failure rearms
    // during the real settle with the clock frozen at the same virtual
    // instant, so the next deadline lands exactly one delay later. A tiny
    // slop of ≤10ms absorbs the 5ms safety nudge between chunks.
    const settle = () => new Promise((resolve) => setTimeout(resolve, 150));
    await settle();
    const gaps: number[] = [];
    for (const delay of [15_000, 30_000, 45_000, 45_000, 45_000]) {
      const before = (await starts()).length;
      await cpage.clock.runFor(delay);
      await expect
        .poll(async () => {
          await cpage.clock.runFor(5);
          return (await starts()).length;
        }, { intervals: [25], timeout: 15_000 })
        .toBe(before + 1);
      const arr = await starts();
      expect(arr.length, "exactly one backoff-driven poll per step").toBe(before + 1);
      gaps.push(arr[before] - arr[before - 1]);
      await settle();
    }
    // Exponential (interval * 2^failures, 75% pinned jitter) and then BOUNDED:
    // the 60s cap floors the cadence at 45s instead of growing forever. The
    // first step (7.5s) was asserted above; these double from it: 15s = 2×7.5s,
    // 30s = 2×15s, then the cap holds.
    const near = (gap: number, delay: number, label: string) =>
      expect(Math.abs(gap - delay), `${label}: gap ≈ ${delay}ms (≤10ms boundary slop)`).toBeLessThanOrEqual(10);
    near(gaps[0], 15_000, "second step doubles");
    near(gaps[1], 30_000, "third step doubles again");
    for (const gap of gaps.slice(2)) expect(gap, "the cap floors the cadence at ~45s").toBeLessThanOrEqual(45_010);
    for (const gap of gaps) expect(gap, "no gap exceeds the capped delay").toBeLessThanOrEqual(45_010);

    // Bounded over the long run: five more virtual minutes at the capped
    // cadence cost ~7 polls, where the old fixed 5s interval would have
    // fired ~60.
    const beforeBurn = (await starts()).length;
    await cpage.clock.runFor(300_000);
    await settle();
    const burned = (await starts()).length - beforeBurn;
    expect(burned, "a five-minute outage at the cap costs ~7 polls, not ~60").toBeLessThanOrEqual(8);
    expect(errors, "no unhandled rejection across the whole outage").toEqual([]);
  } finally {
    await clockContext.close();
  }
});

test("a success resets the cadence to base and the failure ladder to fresh", async () => {
  setModes("abort");
  await mount();
  await expect(pollBanner()).toHaveAttribute("data-health", "unreachable", { timeout: 10_000 });

  // Recover through the manual refresh: it succeeds immediately (no waiting
  // out the armed 7.5s backoff), resets the failure counter and rearms the
  // loop at the base interval.
  setModes("ok");
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(pollBanner()).toHaveCount(0, { timeout: 5_000 });

  // Back under outage: the poll after the success must come at the BASE
  // interval (the success rearmed base cadence, not a leftover backoff
  // step), and the one after that at a FRESH first backoff step (7.5s) — an
  // unreset failure counter would wait 15s there.
  setModes("abort");
  await expect.poll(() => counts.status, { timeout: 15_000 }).toBeGreaterThanOrEqual(4);
  const n = times.status.length;
  const gapBase = times.status[n - 2] - times.status[n - 3];
  const gapFresh = times.status[n - 1] - times.status[n - 2];
  expect(gapBase, "success re-arms the base interval (3.75s pinned), not 7.5s").toBeLessThanOrEqual(5_000);
  expect(gapFresh, "a new failure starts a fresh 7.5s ladder, not 15s").toBeGreaterThanOrEqual(6_800);
  expect(gapFresh).toBeLessThanOrEqual(11_000);
  expect(pageErrors).toEqual([]);
});

test("the loop pauses while the tab is hidden and re-kicks on visibilitychange", async () => {
  await mount();
  await expect.poll(() => counts.status).toBeGreaterThanOrEqual(1);
  const baseline = counts.status;

  await setHidden(true);
  await page.waitForTimeout(5_000); // longer than the exact 3.75s cadence
  expect(counts.status, "no poll fires while the tab is hidden").toBe(baseline);

  await setHidden(false);
  await expect.poll(() => counts.status, "becoming visible polls immediately").toBe(baseline + 1, { timeout: 3_000 });
  expect(pageErrors).toEqual([]);
});

test("the loop pauses while the browser is offline and re-kicks on going back online", async () => {
  await mount();
  await expect.poll(() => counts.status).toBeGreaterThanOrEqual(1);
  const baseline = counts.status;

  await setOnline(false);
  await page.waitForTimeout(5_000);
  expect(counts.status, "no poll fires while offline").toBe(baseline);

  await setOnline(true);
  await expect.poll(() => counts.status, "the online event polls immediately").toBe(baseline + 1, { timeout: 3_000 });
  expect(pageErrors).toEqual([]);
});

test("an unmount aborts the in-flight patch-feed request and stops both loops", async () => {
  ctl.reviewsDelayMs = 20_000; // the request outlives the page unless aborted
  await mount();
  await page.getByRole("button", { name: `completed ${RUN_ID} 2/5 promoted` }).click();
  await expect.poll(() => counts.reviews, "selecting the run polls its patch feed").toBeGreaterThanOrEqual(1);

  const abortedReviews = () =>
    page.evaluate(() =>
      (window as unknown as { __rsiFails: Array<{ url: string; name: string }> }).__rsiFails.filter((f) =>
        f.url.includes("/reviews"),
      ),
    );

  // SPA navigation unmounts the page while the fetch is in flight; the app's
  // own AbortController must reject the fetch as AbortError.
  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByRole("link", { name: "RSI" })).toBeVisible();
  await expect
    .poll(abortedReviews, "the in-flight reviews request was aborted on unmount")
    .toContainEqual({ url: expect.stringContaining("/reviews"), name: "AbortError" });

  const statusAtUnmount = counts.status;
  const reviewsAtUnmount = counts.reviews;
  await page.waitForTimeout(4_500); // longer than one steady cadence tick
  expect(counts.status, "the dashboard loop stopped with the page").toBe(statusAtUnmount);
  expect(counts.reviews, "the patch-feed loop stopped with the page").toBe(reviewsAtUnmount);
  expect(pageErrors, "no uncaught error around the unmount").toEqual([]);
});

test("a slow patch-feed response never overlaps the next poll", async () => {
  await mount();
  await page.getByRole("button", { name: `completed ${RUN_ID} 2/5 promoted` }).click();
  await expect.poll(() => counts.reviews).toBeGreaterThanOrEqual(1);

  // Leave the page FIRST, then arm the delay and clear the feed counters:
  // with the page unmounted nothing can fire, so the next reviews request is
  // exactly the slow one this test selects.
  await page.getByRole("link", { name: "Dashboard" }).click();
  ctl.reviewsDelayMs = 2_500;
  counts.reviews = 0;
  times.reviews.splice(0);
  await page.getByRole("link", { name: "RSI" }).click();
  await page.getByRole("button", { name: `completed ${RUN_ID} 2/5 promoted` }).click();
  await expect.poll(() => counts.reviews).toBe(1);

  await page.waitForTimeout(2_000); // mid-flight: 0.5s before the response lands
  expect(counts.reviews, "no second request while the first is in flight").toBe(1);
  await expect(page.getByTestId("rsi-reviews-health")).toHaveCount(0);

  await expect.poll(() => counts.reviews, "the next poll fires only after the slow one settled").toBe(2, {
    timeout: 10_000,
  });
  const gap = times.reviews[1] - times.reviews[0];
  // No-overlap schedule: 2.5s response + 3.0s cadence ≈ 5.5s. A setInterval
  // loop would have fired the second request at ~4.0s, mid-flight.
  expect(gap, "second request waited for the slow response plus one cadence").toBeGreaterThanOrEqual(4_800);
  expect(pageErrors).toEqual([]);
});
