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
    await mockModels(page, () => ({ status: 200, body: JSON.stringify({ models: ["gw-alpha", "gw-beta"] }) }));
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
      { respond: () => ({ status: 200, body: JSON.stringify({ models: [] }) }), testid: "model-error-empty", text: /empty model catalog/ },
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
      return calls <= 2 ? null : { status: 200, body: JSON.stringify({ models: ["gw-recovered"] }) };
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
    await mockModels(page, () => ({ status: 200, body: JSON.stringify({ models: ["gw-alpha"] }) }));
    await gotoHiveStep(page);

    await page.getByTestId("model-manual-toggle").click();
    await expect(page.getByTestId("model-discovery-status")).toContainText("UNVERIFIED");
    await page.locator('input[placeholder="Hive Conductor"]').fill("Test Hive");
    await expect(page.locator("button", { hasText: "next" })).toBeDisabled();

    await page.getByTestId("unverified-ack").getByRole("checkbox").check();
    await expect(page.locator("button", { hasText: "next" })).toBeEnabled();
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
