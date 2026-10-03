// M3-B7 (#97): degraded mode is a user-facing operating state.
//
// /health computes `degraded_services` — which optional capabilities are
// degraded and why. The app shell renders that list in a banner
// (DegradedBanner) so an operator sees the impact without reading container
// logs, and `hctl status` (CLI page) prints the same list. Both halves are
// pinned here against route-intercepted /health payloads, following the
// established pattern in setup.spec.ts.
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
    await page.route("**/health", (r) => r.fulfill({ json: DEGRADED_HEALTH }));
    await page.route("**/v1/agents", (r) => r.fulfill({ json: [] }));
    await page.route("**/v1/mcp/servers", (r) => r.fulfill({ json: [] }));

    await page.goto("/cli");

    const status = page.getByText("hctl status", { exact: false }).first();
    await expect(status).toBeVisible();
    await expect(page.getByText("! degraded: llm_gateway", { exact: false })).toBeVisible();
    await expect(page.getByText("! degraded: router:routes.design", { exact: false })).toBeVisible();
  });
});
