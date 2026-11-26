/**
 * The shell paints its chrome before the auth chain resolves, and the two
 * probes that gate it run together, not in series (#1408).
 *
 * `App.tsx` used to await `/v1/setup/status`, then `/v1/auth/whoami`, one
 * after the other, showing a plain "loading hive..." sentence the whole
 * time. `whoami` never depended on `setup/status`'s answer -- it reports
 * unauthenticated either way before setup finishes, since no session cookie
 * exists yet -- so the second round trip bought nothing but the wait. Both
 * now fire together, and the placeholder is the real shell's sidebar-plus-
 * content grid rather than a sentence.
 */

import { test, expect, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test("setup-status and whoami are requested together, not one after the other", async ({
  page,
}) => {
  await setupIfNeeded(page);

  // Cold script loading must not be mistaken for serialized auth probes.
  // This exceeds the old 300ms sleep even on a fast local machine.
  await page.route("**/*.js", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600));
    await route.continue();
  });

  // A fast local backend answers both probes in a few milliseconds either
  // way, so timing a normal run cannot tell serial from parallel apart.
  // Holding setup-status open makes the question deterministic: whoami's
  // request either starts while setup-status is still pending (parallel),
  // or waits for it to resolve first (serial) and is never seen here.
  let releaseSetupStatus: () => void = () => {};
  const setupStatusHeld = new Promise<void>((resolve) => {
    releaseSetupStatus = resolve;
  });
  await page.route("**/v1/setup/status", async (route) => {
    await setupStatusHeld;
    await route.continue();
  });

  try {
    // Register before navigation so even an immediate whoami is observed.
    // Setup remains held until BOTH requests arrive: serial code still fails,
    // regardless of how long the browser takes to load and execute the app.
    await Promise.all([
      page.waitForRequest("**/v1/setup/status", { timeout: 5000 }),
      page.waitForRequest("**/v1/auth/whoami", { timeout: 5000 }),
      page.goto("/", { waitUntil: "commit" }),
    ]);
  } finally {
    releaseSetupStatus();
    await page.unroute("**/v1/setup/status");
  }
});

async function firstPaintText(page: Page): Promise<string> {
  return page.evaluate(() => document.body.innerText);
}

test("the shell skeleton, not a loading sentence, is what first paints", async ({ page }) => {
  await setupIfNeeded(page);
  // Slow the two probes so the skeleton has time to be observed, the same
  // way a real slow link would (#1408's own evidence: cold-load timing).
  await page.route("**/v1/setup/status", async (route) => {
    await new Promise((r) => setTimeout(r, 400));
    await route.continue();
  });

  const navigation = page.goto("/", { waitUntil: "commit" });
  await page.waitForSelector('[aria-label="Loading Hive Conductor"]', { timeout: 5000 });
  const skeleton = page.getByLabel("Loading Hive Conductor");
  await expect(skeleton).toBeVisible();
  await expect(skeleton).toHaveAttribute("aria-busy", "true");
  // The old placeholder was exactly this sentence; it must be gone.
  expect(await firstPaintText(page)).not.toContain("loading hive...");
  await navigation;
  await page.unroute("**/v1/setup/status");
});

test("the shell chrome appears before the auth chain finishes for a signed-in user", async ({
  page,
}) => {
  await setupIfNeeded(page);
  await loginAsAdmin(page);

  // Let the login page settle before this test starts measuring. Logging in
  // fires two more whoami calls of its own -- AuthGuard's handleAuthenticated
  // (loadSession) and Login.tsx's completeAuth each fetch /v1/auth/whoami
  // after the login POST -- and both must be done before the steps below:
  // the cache purge must come after the last cache-writing call, and the
  // route further down must hold the navigation's whoami, not a login-page
  // leftover. The shell being usable is the fact that proves the calls are
  // done: the redirect they gate is what renders it.
  await expect(page.getByRole("link", { name: "Chat", exact: true })).toBeVisible({
    timeout: 15000,
  });

  // Each settled login-page whoami answered over the network and wrote the
  // authenticated response into the browser's HTTP cache -- under the exact
  // URL the navigation below fetches. A response served from cache never
  // reaches the network layer, so a route cannot intercept it: the shell
  // would then finish before this test has seen the skeleton, which is the
  // #1801 flake (observed on a PR whose diff cannot reach the Conductor UI).
  // Drop every cached entry so the navigation's whoami must go out over the
  // network. The e2e project is chromium-only (playwright.config.ts), so a
  // CDP session is available; the session cookie lives in cookie storage,
  // not the cache, and survives the purge.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.clearBrowserCache");
  await cdp.detach();

  // Hold whoami's RESPONSE open on a promise this test resolves after the
  // skeleton assertions, instead of a fixed sleep: a fixed 400 ms made the
  // loading window likely rather than certain, which is exactly the #1801
  // failure. While held, AuthGuard's `ready` cannot flip (App.tsx awaits
  // whoami once setup is confirmed complete), so the skeleton cannot unmount
  // under the assertions below.
  let releaseWhoami: () => void = () => {};
  const whoamiReleased = new Promise<void>((resolve) => {
    releaseWhoami = resolve;
  });
  let whoamiHeldResolve: () => void = () => {};
  const whoamiHeld = new Promise<void>((resolve) => {
    whoamiHeldResolve = resolve;
  });
  await page.route("**/v1/auth/whoami", async (route) => {
    whoamiHeldResolve();
    await whoamiReleased;
    await route.continue();
  });

  const navigation = page.goto("/", { waitUntil: "commit" });
  // The interception is the fact the assertions stand on, so wait for it
  // explicitly and bound the wait: a whoami that never reaches the route
  // (a cache the purge missed, or a future cache layer) is then reported as
  // that, not as a shell that silently never finished loading.
  let interceptionTimeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      whoamiHeld,
      new Promise<never>((_, reject) => {
        interceptionTimeout = setTimeout(() => {
          reject(
            new Error(
              "no /v1/auth/whoami request was intercepted during the navigation; the loading skeleton cannot be observed without one",
            ),
          );
        }, 5000);
      }),
    ]);
  } finally {
    clearTimeout(interceptionTimeout);
  }
  await page.waitForSelector('[aria-label="Loading Hive Conductor"]', { timeout: 5000 });
  await expect(page.getByLabel("Loading Hive Conductor")).toBeVisible();
  releaseWhoami();
  await navigation;
  // Workspace-independent, and present at any viewport width: a fresh admin
  // account may hold no workspace, so the tab bar is not guaranteed, and the
  // hamburger only shows at narrow widths. The persistent nav rail is
  // neither.
  await expect(page.getByRole("link", { name: "Chat", exact: true })).toBeVisible({
    timeout: 15000,
  });
  await page.unroute("**/v1/auth/whoami");
});

test("a hung whoami does not hold up the setup wizard on a fresh instance", async ({ page }) => {
  // Firing both probes together must not mean waiting on both: a fresh,
  // unconfigured instance only needs setup-status to know to show the
  // wizard. Awaiting whoami's response body regardless -- the original form
  // of the #1408 fix -- meant a whoami that never resolves left a new
  // operator on the skeleton forever, with no way to reach Setup at all.
  await page.route("**/v1/setup/status", async (route) => {
    await route.fulfill({ json: { setup_complete: false } });
  });
  await page.route("**/v1/auth/whoami", () => {
    // Never fulfilled or continued: this request hangs for the test's life.
  });

  await page.goto("/", { waitUntil: "commit" });
  await expect(page.getByLabel("Conductor name", { exact: true })).toBeVisible({
    timeout: 5000,
  });

  await page.unroute("**/v1/setup/status");
  await page.unroute("**/v1/auth/whoami");
});
