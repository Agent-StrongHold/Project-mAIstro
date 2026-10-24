// M3-B7 (#97): degraded mode is a user-facing operating state.
//
// /health computes `degraded_services` — which optional capabilities are
// degraded and why. The app shell renders that list in a banner
// (DegradedBanner) so an operator sees the impact without reading container
// logs. Since #292, `hctl status` (CLI page) renders the same list verbatim
// as backend-computed `POST /v1/cli/exec` output — the page no longer
// computes anything client-side — so the CLI half is pinned by fulfilling
// the contract route exactly as the backend answers on a degraded stack
// (the computation itself is pinned at route level in
// test_degraded_mode_surface.py). Both halves follow the established
// pattern in setup.spec.ts.
//
// The whoami/setup routes are intercepted too: the banner lives inside the
// authenticated shell, and this spec must not depend on the deployment's
// provisioning state.
import { test, expect } from "@playwright/test";

const USER = {
  authenticated: true,
  user: {
    id: "e2e-user",
    username: "e2e",
    role: "admin",
    permissions: [],
    did: null,
    elevated: false,
    elevated_until: null,
  },
};

const DEGRADED_HEALTH = {
  status: "ok",
  degraded: true,
  degraded_services: [
    {
      service: "llm_gateway",
      reason: "no LLM gateway configured (set LITELLM_API_BASE or LITELLM_PROXY_URL)",
    },
    { service: "router:routes.design", reason: "ImportError: cannot import name 'engine'" },
  ],
};

const HEALTHY_HEALTH = { status: "ok", degraded: false, degraded_services: [] };

test.describe("Degraded mode (M3-B7)", () => {
  test.beforeEach(async ({ page }) => {
    // The onboarding modal renders over the shell until dismissed once; mark
    // it seen so the assertions below see the banner, not the wizard.
    await page.addInitScript(() => localStorage.setItem("hive_onboarded", "1"));
  });

  test("shell banner names which optional services are degraded", async ({ page }) => {
    await page.route("**/v1/setup/status", (r) => r.fulfill({ json: { setup_complete: true } }));
    await page.route("**/v1/auth/whoami", (r) => r.fulfill({ json: USER }));
    await page.route("**/health", (r) => r.fulfill({ json: DEGRADED_HEALTH }));

    await page.goto("/dashboard");

    const banner = page.getByTestId("degraded-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Degraded mode");
    await expect(banner).toContainText("llm_gateway");
    await expect(banner).toContainText("no LLM gateway configured");
    await expect(banner).toContainText("router:routes.design");
  });

  test("shell stays silent when every optional service is healthy", async ({ page }) => {
    await page.route("**/v1/setup/status", (r) => r.fulfill({ json: { setup_complete: true } }));
    await page.route("**/v1/auth/whoami", (r) => r.fulfill({ json: USER }));
    await page.route("**/health", (r) => r.fulfill({ json: HEALTHY_HEALTH }));

    await page.goto("/dashboard");

    await expect(page.getByTestId("degraded-banner")).toHaveCount(0);
  });

  test("hctl status prints the degraded services with reasons", async ({ page }) => {
    await page.route("**/v1/setup/status", (r) => r.fulfill({ json: { setup_complete: true } }));
    await page.route("**/v1/auth/whoami", (r) => r.fulfill({ json: USER }));
    // #292: the CLI page renders backend exec output verbatim; it computes
    // nothing itself. Fulfill the contract route the way the backend's
    // `hctl status` handler answers on a degraded stack (its degraded list
    // comes from the same /health computation pinned above and at route
    // level), and pin the page's rendering of it.
    await page.route("**/v1/cli/sessions", (r) => r.fulfill({ json: [] }));
    await page.route("**/v1/cli/exec", (r) =>
      r.fulfill({
        json: {
          session: { id: "default", cwd: "/", history: [] },
          command: "hctl status",
          lines: [
            "\u2713 hive-conductor running (uptime 60s)",
            "\u2713 router model: test-model",
            "\u2713 0 agents ready",
            "\u2713 0/0 MCP servers connected",
            "! degraded: llm_gateway \u2014 no LLM gateway configured (set LITELLM_API_BASE or LITELLM_PROXY_URL)",
            "! degraded: router:routes.design \u2014 ImportError: cannot import name 'engine'",
          ],
        },
      }),
    );

    await page.goto("/cli");

    await expect(page.getByText("$ hctl status").first()).toBeVisible();
    await expect(page.getByText("! degraded: llm_gateway", { exact: false })).toBeVisible();
    await expect(page.getByText("! degraded: router:routes.design", { exact: false })).toBeVisible();
  });
});
