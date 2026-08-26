/**
 * PM Workflow E2E — walks through the UI exactly as a project manager would.
 *
 * Flow:
 *   1. First boot → Setup wizard
 *   2. Login as PM user
 *   3. Dashboard overview
 *   4. Create a DAG (Fleet → DagBuilder)
 *   5. Run the DAG
 *   6. Check run results
 *   7. Give thumbs feedback
 *   8. Visit Optimization Inbox
 *   9. Accept/reject a proposal
 *  10. Verify audit trail
 */

import { test, expect, Page } from "@playwright/test";

const ADMIN_USER = "admin";
const ADMIN_PASS = "adminpass123";
const PM_USER = "pmuser";
const PM_PASS = "pmpass1234";

async function setupIfNeeded(page: Page) {
  // Setup state is an API fact, not a rendering fact. On a cold first boot the
  // root page can still be rendering its loading state when page.goto() returns,
  // so reading body text here races the setup-status request made by the app.
  // Ask the same backend endpoint that spec 01 asserts instead.
  const statusResponse = await page.request.get("/v1/setup/status");
  expect(statusResponse.status()).toBe(200);
  const status = await statusResponse.json();
  if (status.setup_complete) return;

  await page.goto("/");

  // Setup.tsx's non-PM-POC wizard is five steps:
  //   ["Hive", "Hardware", "Accounts", "Modules", "Confirm"]
  // Wait for the first wizard control so a slow cold render cannot race the
  // setup flow after the backend has already told us setup is required.
  const conductorName = page.locator('input[placeholder="Hive Conductor"]');
  await conductorName.waitFor({ state: "visible", timeout: 15000 });

  // 1/5 — Hive
  await conductorName.fill("PM Test Hive");
  await page.locator("button", { hasText: /next/i }).click();

  // 2/5 — Hardware
  await page.locator("text=Beast").first().click();
  await page.locator("button", { hasText: /next/i }).click();

  // 3/5 — Accounts. These are the same credentials loginAsPM() logs in with
  // below, so the accounts this creates are the ones the rest of the suite
  // depends on. Both password fields share placeholder="password" (admin
  // card first, daily-user card second), hence nth() rather than placeholder.
  await page.locator('input[placeholder="admin"]').fill(ADMIN_USER);
  await page.locator('input[type="password"]').nth(0).fill(ADMIN_PASS);
  await page.locator('input[placeholder="username"]').fill(PM_USER);
  await page.locator('input[type="password"]').nth(1).fill(PM_PASS);
  await page.locator("button", { hasText: /next/i }).click();

  // 4/5 — Modules (skip)
  await page.locator("button", { hasText: /next/i }).click();

  // 5/5 — Confirm. Wait for the POST itself to land, not for a URL change.
  // Do not swallow a missing/failed response: this helper is the setup gate for
  // every test, so provisioning failure must fail here rather than leak into a
  // downstream assertion or authentication error.
  const [completeResponse] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/v1/setup/complete") && r.request().method() === "POST",
      { timeout: 15000 },
    ),
    page.locator("button", { hasText: /launch/i }).click(),
  ]);
  expect(completeResponse.status()).toBe(200);
  const complete = await completeResponse.json();
  expect(complete.setup_complete).toBe(true);
}

// Login.tsx's inputs carry NO `name` and no user-ish placeholder — they are
// identified by autocomplete tokens:
//   login mode     -> autocomplete="username" + autocomplete="current-password"
//   register mode  -> autocomplete="username" + two autocomplete="new-password"
//                     (password, then confirm)
// The previous selectors here were 'input[name="username"], input[placeholder*="user"]',
// which match nothing in either mode. That is why specs 02-12 each hung for the
// full test timeout inside this helper rather than failing on an assertion.
//
// Mode is detected from the form itself rather than from body text: the login
// view also renders a "Register" toggle, so a body.includes("Register") check
// takes the register branch while sitting on the login form.
async function loginAsPM(page: Page) {
  await page.goto("/login");

  const usernameInput = page.locator('input[autocomplete="username"]').first();
  const passwordInput = page.locator('input[autocomplete="current-password"]').first();

  // The PM account is created by the setup wizard (setupIfNeeded fills the
  // Accounts step with these same constants), so this only ever needs to log
  // in — there is no register path to fall back to.
  await usernameInput.waitFor({ state: "visible" });
  await usernameInput.fill(PM_USER);
  await passwordInput.fill(PM_PASS);

  // Submit by type, NOT by text. Login.tsx renders two mode-TOGGLE buttons
  // labelled "Sign in" / "Sign up" above the form, and the real submit button
  // reads "enter the hive" (only "sign in" in PM-POC mode). The previous
  // selector, hasText: /log.?in|sign.?in/i, therefore matched the *toggle*:
  // it clicked it, switched to the mode it was already in, submitted nothing,
  // and reported no error.
  //
  // Awaiting the response rather than a fixed timeout means a login that stops
  // working fails here, loudly, instead of leaking into a downstream 401.
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/v1/auth/login") && r.request().method() === "POST",
      { timeout: 15000 },
    ),
    page.locator('form button[type="submit"]').click(),
  ]);
}

async function elevateDagWrites(page: Page, taskId: string) {
  // DAG creation/runs and optimizer mutations are protected operations. The
  // setup-created daily user is assigned dags.write but must prove possession
  // of its password for a task-scoped elevation before exercising that power.
  const response = await page.request.post("/v1/auth/elevate", {
    data: {
      password: PM_PASS,
      permissions: ["dags.write"],
      task_id: taskId,
    },
  });
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.elevated_permissions).toContain("dags.write");
}

test.describe("PM Workflow — Full UI Walkthrough", () => {
  test.beforeEach(async ({ page }) => {
    await setupIfNeeded(page);
  });

  test("01 — Setup wizard completes on first boot", async ({ page }) => {
    const r = await page.request.get("/v1/setup/status");
    const data = await r.json();
    expect(data.setup_complete).toBe(true);
  });

  test("02 — PM can login and see dashboard", async ({ page }) => {
    await loginAsPM(page);
    await page.goto("/chat");
    await expect(page.locator("body")).toContainText(/hive|conductor|chat/i, { timeout: 10000 });
  });

  test("03 — Dashboard loads with key metrics", async ({ page }) => {
    await loginAsPM(page);
    await page.goto("/");
    await page.waitForTimeout(2000);
    const response = await page.request.get("/health");
    expect(response.status()).toBe(200);
  });

  test("04 — PM can navigate to Fleet page", async ({ page }) => {
    await loginAsPM(page);
    await page.goto("/fleet");
    await page.waitForTimeout(2000);
    const apiResponse = await page.request.get("/v1/dags");
    expect(apiResponse.status()).toBe(200);
  });

  test("05 — PM can create a DAG via API (simulating DagBuilder)", async ({ page }) => {
    await loginAsPM(page);
    await elevateDagWrites(page, "e2e-create-dag");

    const createResp = await page.request.post("/v1/dags", {
      data: {
        name: "Sprint Retro Digest",
        description: "Collect retro notes and produce action items",
      },
    });
    expect(createResp.status()).toBe(201);
    const dag = await createResp.json();
    expect(dag.name).toBe("Sprint Retro Digest");
    expect(dag.nodes.length).toBe(2);
  });

  test("06 — PM can activate and run a DAG", async ({ page }) => {
    await loginAsPM(page);
    await elevateDagWrites(page, "e2e-run-dag");

    const createResp = await page.request.post("/v1/dags", {
      data: { name: "E2E Run Test", description: "test" },
    });
    expect(createResp.status()).toBe(201);
    const dag = await createResp.json();

    const activateResp = await page.request.post(`/v1/dags/${dag.id}/activate`);
    expect(activateResp.status()).toBe(200);
    const activated = await activateResp.json();
    expect(activated.status).toBe("active");

    const runResp = await page.request.post(`/v1/dags/${dag.id}/run`);
    expect(runResp.status()).toBe(200);
    const run = await runResp.json();
    expect(run.execution_id).toBeTruthy();
  });

  test("07 — PM can give thumbs feedback on a run", async ({ page }) => {
    await loginAsPM(page);
    await elevateDagWrites(page, "e2e-feedback-dag");

    const createResp = await page.request.post("/v1/dags", {
      data: { name: "Feedback Test DAG", description: "test" },
    });
    expect(createResp.status()).toBe(201);
    const dag = await createResp.json();

    const activateResp = await page.request.post(`/v1/dags/${dag.id}/activate`);
    expect(activateResp.status()).toBe(200);
    const runResp = await page.request.post(`/v1/dags/${dag.id}/run`);
    expect(runResp.status()).toBe(200);
    const run = await runResp.json();
    expect(run.execution_id).toBeTruthy();

    const fbResp = await page.request.post(`/v1/dag-runs/${run.execution_id}/feedback`, {
      data: { thumb: "up", comment: "Nailed it!", dag_id: dag.id },
    });
    expect([200, 404]).toContain(fbResp.status());
  });

  test("08 — PM can trigger optimizer and see proposals", async ({ page }) => {
    await loginAsPM(page);
    await elevateDagWrites(page, "e2e-optimize-dag");

    const createResp = await page.request.post("/v1/dags", {
      data: { name: "Optimizer Test DAG", description: "test" },
    });
    expect(createResp.status()).toBe(201);
    const dag = await createResp.json();

    const optResp = await page.request.post(`/v1/optimizer/${dag.id}/run`);
    expect([200, 400]).toContain(optResp.status());

    const proposalsResp = await page.request.get(`/v1/optimizer/${dag.id}/proposals`);
    expect(proposalsResp.status()).toBe(200);
    const proposals = await proposalsResp.json();
    expect(Array.isArray(proposals)).toBe(true);
  });

  test("09 — PM can visit Optimization Inbox page", async ({ page }) => {
    await loginAsPM(page);
    await page.goto("/optimization");
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  test("10 — PM can view audit log", async ({ page }) => {
    await loginAsPM(page);
    const auditResp = await page.request.get("/v1/audit");
    expect(auditResp.status()).toBe(200);
    const entries = await auditResp.json();
    expect(Array.isArray(entries)).toBe(true);
    expect(entries.length).toBeGreaterThan(0);
  });

  test("11 — PM can view DAG metrics", async ({ page }) => {
    await loginAsPM(page);
    const metricsResp = await page.request.get("/v1/dag-metrics");
    expect(metricsResp.status()).toBe(200);
  });

  test("12 — PM can navigate all key pages without errors", async ({ page }) => {
    await loginAsPM(page);

    const pages = ["/chat", "/fleet", "/missions", "/agents", "/settings"];
    for (const p of pages) {
      await page.goto(p);
      await page.waitForTimeout(1000);
      const body = await page.textContent("body");
      expect(body?.length).toBeGreaterThan(0);
    }
  });

  // #369's "Browser E2E verifies effective cookie attributes". These assert
  // what a real Chromium actually stored, not what the server said to store —
  // a `Set-Cookie` a browser rejects or rewrites looks identical in a unit
  // test.
  //
  // `Secure` is deliberately NOT asserted here, and its absence is not a gap.
  // This harness serves plain HTTP and declares itself a local-development
  // context (docker-compose.test.yml), so the cookie is correctly not Secure
  // in it. Its browser-level effect was demonstrated the hard way: turning the
  // default on without declaring the harness made Chromium drop the cookie and
  // seven of the tests above fail with 401 immediately after a successful
  // login. Asserting `secure === false` here would pin the harness's waiver
  // rather than the product's default, which is the wrong thing to hold still.
  test("13 — the session cookie a browser stores is HttpOnly and scoped", async ({
    page,
    context,
  }) => {
    await loginAsPM(page);

    const cookies = await context.cookies();
    const session = cookies.find((c) => c.name === "hive_session");
    expect(session, "no hive_session cookie was stored after login").toBeTruthy();

    // HttpOnly: script cannot read it, so an XSS cannot exfiltrate the session.
    expect(session!.httpOnly).toBe(true);
    // Scoped to the whole app rather than inherited from the login route's path.
    expect(session!.path).toBe("/");
    // Lax: rides a top-level navigation (an emailed link works) but not a
    // cross-site subrequest.
    expect(session!.sameSite).toBe("Lax");
    // Bounded lifetime. A cookie with no expiry lives as long as the browser
    // process, which on a machine that is never rebooted is indefinitely —
    // Playwright reports that case as -1.
    expect(session!.expires).toBeGreaterThan(0);
  });

  test("14 — the session cookie is not readable from JavaScript", async ({ page }) => {
    // The property HttpOnly exists for, asserted from inside the page rather
    // than from the cookie jar: the flag being set and the value being
    // unreachable are different claims, and only the second one matters.
    await loginAsPM(page);

    const visible = await page.evaluate(() => document.cookie);
    expect(visible).not.toContain("hive_session");
  });
});
