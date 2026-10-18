/**
 * Authorization surface E2E (#373): navigation and controls must derive from
 * the same live capability policy the API enforces — never from a cached
 * snapshot, and never from a frontend-only notion of a role.
 *
 * Everything here drives a real deployment over real HTTP, through the same
 * login the other specs use (session.ts). The admin (break-glass) account is
 * driven through the `request` fixture's own cookie jar so granting a
 * permission to the daily account never clobbers the browser's session.
 *
 * The hive under test runs with HIVE_ELEVATION_TTL_SECONDS=8 (see
 * docker-compose.test.yml) so the expiry case proves a real grant expiring
 * server-side inside the CI test budget instead of mocking the clock.
 */

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { ADMIN_PASS, ADMIN_USER, loginAsAdmin, loginAsPM, PM_PASS, setupIfNeeded } from "./session";

const RSI_HEADING = "RSI — Recursive Self-Improvement";
const RSI_SIDEBAR_LINK = 'a.nav-icon:has-text("RSI")';
const LOCKED_LINK = 'a.nav-icon:has-text("locked")';

/**
 * Log the break-glass admin into an APIRequestContext's own cookie jar. The
 * `request` fixture mints a fresh context that shares nothing with the page
 * (unlike page.request), so anything it calls before this is unauthenticated.
 */
async function loginAdminJar(admin: APIRequestContext) {
  const login = await admin.post("/v1/auth/login", {
    data: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  expect(login.status()).toBe(200);
}

/**
 * set_user_permissions REPLACES a user's whole assigned set. Passing the
 * wizard-assigned `dags.write` baseline along keeps the pm-workflow specs'
 * DAG elevation usable downstream — dropping it here would strand them.
 */
async function setPmPermissions(admin: APIRequestContext, pm: Page, permissions: string[]) {
  const who = await pm.request.get("/v1/auth/whoami");
  expect(who.status()).toBe(200);
  const { user } = await who.json();
  // whoami only carries a user for a logged-in browser session — calling
  // this before loginAsPM would fail here, not with a confusing PATCH 401.
  expect(user, "pm page must have a session before setPmPermissions").toBeTruthy();
  const granted = await admin.patch(`/v1/auth/users/${user.id}/permissions`, {
    data: { permissions },
  });
  expect(granted.status()).toBe(200);
}

async function grantRsiToPm(admin: APIRequestContext, pm: Page) {
  // The `request` fixture's context starts with an empty cookie jar — an
  // unauthenticated PATCH here would get the middleware's 401, not a grant.
  // Logging the admin into THIS jar also keeps the admin session away from
  // the browser, so the PM session under test is never clobbered.
  await loginAdminJar(admin);
  await setPmPermissions(admin, pm, ["dags.write", "rsi.execute"]);
}

test.describe("authorization reflects effective capability policy", () => {
  test.beforeEach(async ({ page }) => {
    // The onboarding tour is itself a dialog covering the whole app on a fresh
    // browser context (modal-a11y.spec.ts seeds the same fact). These tests
    // exercise authorization surfaces, not the tour.
    await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
  });

  test("admin: every surface effective, deep link into RSI works", async ({ page }) => {
    await setupIfNeeded(page);
    await loginAsAdmin(page);

    const caps = await page.request.get("/v1/auth/capabilities");
    // APIResponse.headers is a method, not a property — and the no-store
    // contract is what keeps a browser (or a shared proxy) from serving a
    // stale capability snapshot after a permission change.
    expect((await caps.headers())["cache-control"]).toBe("no-store");
    const body = await caps.json();
    expect(body.version).toBe("hive-http-capabilities-v1");
    expect(body.role).toBe("admin");
    for (const surface of ["settings", "credentials", "integrations", "rsi"]) {
      expect(body.surfaces[surface].effective, surface).toBe(true);
    }

    // Nav shows RSI, and nothing is marked locked.
    await expect(page.locator(RSI_SIDEBAR_LINK)).toHaveCount(1);
    await expect(page.locator(LOCKED_LINK)).toHaveCount(0);

    // A protected deep link, loaded cold from the server, renders the surface.
    await page.goto("/rsi");
    await expect(page.getByRole("heading", { name: RSI_HEADING })).toBeVisible();

    // Admin controls are actionable, not decorative.
    await page.goto("/settings");
    await expect(page.getByRole("button", { name: "edit", exact: true }).first()).toBeEnabled();
  });

  test("daily user: unauthorized surfaces filtered, controls disabled, API authoritative", async ({
    page,
    request,
  }) => {
    await setupIfNeeded(page);
    await loginAsPM(page);
    // Arrange the no-grant state this test asserts from, whatever earlier
    // tests (or retries) granted: assignments are store-persistent, and the
    // suite must not depend on running against a seedless deployment. The
    // reload is the no-stale-cache contract doing its job — a fresh, no-store
    // snapshot has to reflect the reset immediately.
    await loginAdminJar(request);
    await setPmPermissions(request, page, []);
    await page.reload();

    // RSI is not merely greyed out — it is absent from the nav.
    await expect(page.locator(RSI_SIDEBAR_LINK)).toHaveCount(0);

    const body = await (await page.request.get("/v1/auth/capabilities")).json();
    expect(body.role).toBe("user");
    expect(body.surfaces.rsi.effective).toBe(false);

    // Direct URL access cannot smuggle the surface in: the route renders the
    // safe explanation instead of the protected page.
    await page.goto("/rsi");
    await expect(page.getByText("This surface is not currently actionable")).toBeVisible();
    await expect(
      page.getByText(/Your account does not have rsi\.execute/),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: RSI_HEADING })).toHaveCount(0);

    // UI filtering is convenience only — the API, not the nav, is the gate.
    expect((await page.request.get("/v1/rsi/status")).status()).toBe(403);
    expect(
      (await page.request.patch("/v1/settings", { data: { hive_name: "nope" } })).status(),
    ).toBe(403);

    // The settings/credentials/integrations controls carry the same policy:
    // an explanation plus disabled controls, never an actionable-looking
    // control that is guaranteed to fail.
    await page.goto("/settings");
    await expect(page.getByText("Settings changes is not currently actionable")).toBeVisible();
    await expect(page.getByRole("button", { name: "edit", exact: true }).first()).toBeDisabled();
    await page.goto("/credentials");
    await expect(page.getByText("Credential changes is not currently actionable")).toBeVisible();
    await page.goto("/mcp");
    await expect(page.getByText("Integration changes is not currently actionable")).toBeVisible();
    await expect(page.getByRole("button", { name: "+ add server" })).toBeDisabled();
  });

  test("scoped grant: assignment reaches the UI without a stale snapshot", async ({
    page,
    request,
  }) => {
    await setupIfNeeded(page);
    await loginAsPM(page);
    // Same isolation discipline as the daily-user test: prove the pre-grant
    // nav state from a reset baseline, not from whatever ran before us.
    await loginAdminJar(request);
    await setPmPermissions(request, page, []);
    await page.reload();
    await expect(page.locator(RSI_SIDEBAR_LINK)).toHaveCount(0);

    await grantRsiToPm(request, page);

    // The capabilities contract is no-store, so a fresh load must reflect the
    // assignment immediately — the nav shows RSI as reachable-but-locked.
    await page.reload();
    await expect(page.locator(RSI_SIDEBAR_LINK)).toHaveCount(1);
    await expect(page.locator(LOCKED_LINK)).toHaveCount(1);

    const body = await (await page.request.get("/v1/auth/capabilities")).json();
    expect(body.capabilities["rsi.execute"].assigned).toBe(true);
    expect(body.capabilities["rsi.execute"].effective).toBe(false);
    expect(body.capabilities["rsi.execute"].can_elevate).toBe(true);
    expect(body.capabilities["rsi.execute"].reason).toBe("assigned; self-elevation required");
  });

  test("self-elevation unlocks the granted surface for the task", async ({ page, request }) => {
    await setupIfNeeded(page);
    await loginAsPM(page);
    await grantRsiToPm(request, page);

    await page.goto("/rsi");
    await expect(page.getByText(/This action requires rsi\.execute/)).toBeVisible();
    await page.getByRole("button", { name: "request elevation" }).click();
    await page.locator('input[type="password"]').fill(PM_PASS);

    const elevateResponse = page.waitForResponse(
      (r) => r.url().includes("/v1/auth/elevate") && r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "elevate", exact: true }).click();
    expect((await elevateResponse).status()).toBe(200);

    // The context refreshes its snapshot after elevating, so the boundary
    // lets the real surface through without a manual reload.
    await expect(page.getByRole("heading", { name: RSI_HEADING })).toBeVisible();
    await expect(page.locator(RSI_SIDEBAR_LINK)).toHaveCount(1);
    await expect(page.locator(LOCKED_LINK)).toHaveCount(0);

    // The API agrees — the same call that 403'd pre-elevation now succeeds.
    expect((await page.request.get("/v1/rsi/status")).status()).toBe(200);
  });

  test("revoking the assignment drops an active elevation mid-session", async ({
    page,
    request,
  }) => {
    // Revocation-by-task-completion is machine-tested at the API level
    // (test_api.py::test_elevation_revoked_on_task_completion), but POST
    // /v1/tasks proxies to a maistro-server this harness never provisions
    // (see test_pm_workflow_api.py's skipped test_tasks) — so the browser
    // E2E proves the other revocation door: the admin taking the assignment
    // back while an elevation is still live. effective requires assigned AND
    // elevated, so the grant dies with the assignment, and nothing cached in
    // the UI may keep showing the surface as actionable.
    await setupIfNeeded(page);
    await loginAsPM(page);
    await grantRsiToPm(request, page);

    const elevated = await page.request.post("/v1/auth/elevate", {
      data: { password: PM_PASS, permissions: ["rsi.execute"], task_id: "revoke-e2e" },
    });
    expect(elevated.status()).toBe(200);
    let caps = await (await page.request.get("/v1/auth/capabilities")).json();
    expect(caps.surfaces.rsi.effective).toBe(true);

    await setPmPermissions(request, page, ["dags.write"]);

    caps = await (await page.request.get("/v1/auth/capabilities")).json();
    expect(caps.surfaces.rsi.effective).toBe(false);

    // The API is the gate: the elevated call is refused again.
    expect((await page.request.get("/v1/rsi/status")).status()).toBe(403);

    // And the UI follows on its next load: the surface is neither actionable
    // nor elevatable anymore — the safe explanation, never a control
    // guaranteed to fail.
    await page.goto("/rsi");
    await expect(page.getByText(/Your account does not have rsi\.execute/)).toBeVisible();
  });

  test("a grant expiring mid-session drops back to locked", async ({ page, request }) => {
    await setupIfNeeded(page);
    await loginAsPM(page);
    await grantRsiToPm(request, page);

    const elevated = await page.request.post("/v1/auth/elevate", {
      data: { password: PM_PASS, permissions: ["rsi.execute"], task_id: "expiry-e2e" },
    });
    expect(elevated.status()).toBe(200);
    const elevatedBody = await elevated.json();
    const ttlMs = Date.parse(elevatedBody.elevated_until) - Date.now();
    // The compose harness shortens the TTL (HIVE_ELEVATION_TTL_SECONDS=8);
    // if this fires, the env override did not reach the hive service.
    expect(ttlMs, "test hive must run with a shortened elevation TTL").toBeLessThan(15000);

    let caps = await (await page.request.get("/v1/auth/capabilities")).json();
    expect(caps.surfaces.rsi.effective).toBe(true);

    await page.waitForTimeout(ttlMs + 1500);
    caps = await (await page.request.get("/v1/auth/capabilities")).json();
    expect(caps.surfaces.rsi.effective).toBe(false);
    expect(caps.capabilities["rsi.execute"].reason).toBe("assigned; self-elevation required");

    await page.goto("/rsi");
    await expect(page.getByText(/This action requires rsi\.execute/)).toBeVisible();
  });
});
