import { expect, test, type Page } from "@playwright/test";

// Gateway model discovery in the Setup wizard (#287). The wizard runs
// pre-login, so every gateway failure class must be visible, distinguishable,
// retryable, and never pass for a discovered catalog: these specs mock
// GET /v1/settings/models per class against the dev server and pin the
// wizard's states. The curated fallback list must never be presented as
// successfully discovered gateway state.

async function gotoHiveStep(page: Page) {
  await mockBaseline(page);
  await page.goto("/");
  await expect(page.getByText("🐝 Hive Conductor")).toBeVisible({ timeout: 10000 });
}

function mockModels(page: Page, respond: () => { status: number; body: string } | null) {
  return page.route("**/v1/settings/models", (route) => {
    const response = respond();
    if (response === null) return route.abort();
    return route.fulfill({
      status: response.status,
      contentType: "application/json",
      body: response.body,
    });
  });
}

// The dev server proxies /v1 to whatever backend is up; the wizard specs are
// about the frontend state machine, so pin the app-level routes the wizard
// depends on (registered first: later routes take precedence, and the
// per-test models mock must win over nothing here).
async function mockBaseline(page: Page) {
  await page.route("**/v1/setup/status", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ setup_complete: false }) }),
  );
  await page.route("**/v1/setup/presets", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ presets: {} }) }),
  );
  await page.route("**/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ identity: { status: "operational" } }) }),
  );
}

test.describe("Setup wizard — gateway model discovery", () => {
  test("successful discovery shows the gateway catalog as verified", async ({ page }) => {
    await mockModels(page, () => ({ status: 200, body: JSON.stringify({ models: ["gw-alpha", "gw-beta"], discovered: true, source: "gateway", error: null }) }));
    await gotoHiveStep(page);

    const status = page.getByTestId("model-discovery-status");
    await expect(status).toContainText("2 models discovered from the gateway");
    // The gateway catalog replaces the curated fallback…
    await expect(page.locator("#setup-router-model")).toHaveValue(/gw-(alpha|beta)/);
    // …so no unverified acknowledgement is required and next is enabled.
    await expect(page.getByTestId("unverified-ack")).toHaveCount(0);
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await expect(page.locator("button", { hasText: "next" })).toBeEnabled();
  });

  test("an auth failure is distinguishable and blocks next until acknowledged", async ({ page }) => {
    await mockModels(page, () => ({ status: 401, body: JSON.stringify({ detail: "Not authenticated" }) }));
    await gotoHiveStep(page);

    const alert = page.getByTestId("model-error-auth");
    await expect(alert).toContainText("Gateway authentication failed");
    await expect(page.getByTestId("model-discovery-status")).toContainText("UNVERIFIED");
    // The curated fallback is still usable for offline setup…
    await expect(page.locator("#setup-router-model")).not.toBeEmpty();
    // …but never as verified state: retry is offered and next stays locked.
    await expect(page.getByTestId("model-retry")).toBeVisible();
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await expect(page.locator("button", { hasText: "next" })).toBeDisabled();

    await page.getByTestId("unverified-ack").getByRole("checkbox").check();
    await expect(page.locator("button", { hasText: "next" })).toBeEnabled();
    await page.getByTestId("unverified-ack").getByRole("checkbox").uncheck();
    await expect(page.locator("button", { hasText: "next" })).toBeDisabled();
  });

  test("server, not-found, network, empty, and malformed failures are distinguishable", async ({ page }) => {
    const cases: Array<{ respond: () => { status: number; body: string } | null; testid: string; text: RegExp }> = [
      { respond: () => ({ status: 500, body: "{}" }), testid: "model-error-server", text: /server error/ },
      { respond: () => ({ status: 404, body: "{}" }), testid: "model-error-not_found", text: /not found \(404\)/ },
      { respond: () => null, testid: "model-error-network", text: /Could not reach the gateway/ },
      { respond: () => ({ status: 200, body: JSON.stringify({ models: [], discovered: false, source: "gateway", error: { kind: "empty", message: "The gateway answered but returned an empty model catalog." } }) }), testid: "model-error-empty", text: /empty model catalog/ },
      { respond: () => ({ status: 200, body: JSON.stringify({ models: "oops" }) }), testid: "model-error-malformed", text: /could not be parsed/ },
    ];
    for (const c of cases) {
      await mockModels(page, c.respond);
      await gotoHiveStep(page);
      await expect(page.getByTestId(c.testid)).toContainText(c.text);
      await expect(page.getByTestId("model-retry")).toBeVisible();
    }
  });

  test("retry re-attempts discovery and can clear the failure", async ({ page }) => {
    let calls = 0;
    await mockModels(page, () => {
      calls += 1;
      // StrictMode double-invokes the mount effect, so the first two calls
      // are the paired initial fetches; only the explicit retry is call 3.
      return calls <= 2 ? null : { status: 200, body: JSON.stringify({ models: ["gw-recovered"], discovered: true, source: "gateway", error: null }) };
    });
    await gotoHiveStep(page);

    await expect(page.getByTestId("model-error-network")).toBeVisible();
    await page.getByTestId("model-retry").click();
    const status = page.getByTestId("model-discovery-status");
    await expect(status).toContainText("1 models discovered from the gateway");
    await expect(page.getByTestId("model-error-network")).toHaveCount(0);
    await expect(page.getByTestId("unverified-ack")).toHaveCount(0);
  });

  test("manual entry requires the unverified acknowledgement", async ({ page }) => {
    await mockModels(page, () => ({ status: 200, body: JSON.stringify({ models: ["gw-alpha"], discovered: true, source: "gateway", error: null }) }));
    await gotoHiveStep(page);

    await page.getByTestId("model-manual-toggle").click();
    await expect(page.getByTestId("model-discovery-status")).toContainText("UNVERIFIED");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await expect(page.locator("button", { hasText: "next" })).toBeDisabled();

    await page.getByTestId("unverified-ack").getByRole("checkbox").check();
    await expect(page.locator("button", { hasText: "next" })).toBeEnabled();
  });

  test("a 200 that is not discovered is a cached substitute, never the gateway catalog", async ({ page }) => {
    // The backend answers 200 even when the gateway is unusable: `models` is
    // then the stored-default substitute and `discovered` is false. The
    // wizard must show the backend's failure class (not_configured, tls, …),
    // keep the substitute distinct as the cached default, and demand the
    // unverified acknowledgement — never "N models discovered" (#287).
    const notDiscovered = (kind: string, message: string) => ({
      status: 200,
      body: JSON.stringify({ models: ["stored-default"], discovered: false, source: "stored_default", error: { kind, message } }),
    });
    await mockModels(page, () => notDiscovered("not_configured", "No LLM gateway is configured; the stored default is the only known-good model."));
    await gotoHiveStep(page);

    const status = page.getByTestId("model-discovery-status");
    await expect(status).toContainText("UNVERIFIED");
    await expect(status).not.toContainText("discovered from the gateway");
    await expect(page.getByTestId("model-error-not_configured")).toContainText(/stored default/);
    // The cached substitute is its own provenance state, distinct from the
    // curated suggestions and from a discovered catalog.
    await expect(page.getByTestId("model-cached-default")).toContainText("stored-default");
    await expect(page.getByTestId("model-retry")).toBeVisible();
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await expect(page.locator("button", { hasText: "next" })).toBeDisabled();
    await page.getByTestId("unverified-ack").getByRole("checkbox").check();
    await expect(page.locator("button", { hasText: "next" })).toBeEnabled();

    // A gateway-side TLS failure classified by the backend arrives through
    // the same 200 + metadata contract and renders its own class.
    await mockModels(page, () => notDiscovered("tls", "TLS certificate verification failed while contacting the gateway."));
    await page.getByTestId("model-retry").click();
    await expect(page.getByTestId("model-error-tls")).toContainText(/TLS certificate verification failed/);
  });

  test("the confirm step marks an unverified router model", async ({ page }) => {
    await mockModels(page, () => ({ status: 401, body: JSON.stringify({ detail: "Not authenticated" }) }));
    await gotoHiveStep(page);

    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await page.getByTestId("unverified-ack").getByRole("checkbox").check();
    await page.locator("button", { hasText: "next" }).click();
    // Hardware step: no presets are served by the bare dev server, so next
    // is enabled without a selection (#129 behaviour).
    await page.locator("button", { hasText: "next" }).click();
    await page.getByRole("textbox", { name: "Admin password" }).fill("admin-password-1");
    await page.getByRole("textbox", { name: "Daily user username" }).fill("daily-user");
    await page.getByRole("textbox", { name: "Daily user password" }).fill("daily-password-1");
    await page.locator("button", { hasText: "next" }).click();
    // Modules step needs no selection.
    await expect(page.getByText("Optional modules")).toBeVisible();
    await page.locator("button", { hasText: "next" }).click();
    await expect(page.getByText("Confirm configuration")).toBeVisible();
    await expect(page.getByTestId("router-model-unverified")).toContainText("unverified");
  });
});
