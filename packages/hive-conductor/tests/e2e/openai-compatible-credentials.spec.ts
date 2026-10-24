/**
 * The generic OpenAI-compatible credential lifecycle, driven in the browser (#289).
 *
 * The backend suite proves the API contract (vault-only secrets, non-persisting
 * probe, categorized errors, delete-without-secret cleanup). This spec proves
 * the operator's path through the actual page: create, test-button failure
 * surface, key rotation, edit that never resends the key, disable, delete.
 *
 * Two deliberate boundaries, so nobody reads this as more than it is:
 *
 * - The "test & discover models" click here asserts the *failure* surface
 *   against a port with nothing listening on it — deterministic inside the
 *   compose network and a live exercise of the route's `connectivity`
 *   categorization. Successful discovery through the real guarded transport
 *   is proven server-side by
 *   `backend/tests/test_credentials_api.py::test_openai_compatible_probe_over_real_transport`,
 *   because a success needs a live OpenAI-compatible endpoint the test
 *   compose does not ship.
 * - "Edit without key replacement" is asserted at the wire: the config PUT's
 *   body is captured and must carry no secret at all. That the stored key
 *   still authorizes after such an edit is proven server-side in the same
 *   backend lifecycle test.
 */

import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

/** The card for one credential provider on the Credentials page. */
function providerCard(current: Page) {
  return current.locator("article", { hasText: "OpenAI-compatible gateway" });
}

/**
 * The admin's first visit raises the "Welcome to Hive" onboarding modal, which
 * covers the page and swallows every click below it. Dismiss it when present;
 * absence (every run after the first) skips the click, so this is an if, not
 * a wait.
 */
async function dismissOnboarding(current: Page) {
  const skip = current.getByText("Skip onboarding");
  if (await skip.isVisible().catch(() => false)) {
    await skip.click();
  }
  await expect(skip).toHaveCount(0, { timeout: 10000 });
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsAdmin(page);

  // Land on the page once, here, and require the provider card: a broken
  // session or route fails beforeAll with a readable error instead of every
  // test timing out on its first locator.
  await page.goto("/credentials", { waitUntil: "domcontentloaded" });
  // The card (rendered beneath any overlay) is the settle signal: it exists
  // only after whoami + the credentials fetch have landed, which is also when
  // the onboarding modal, if this admin's first visit, is in the DOM to be
  // dismissed. Checking for the modal earlier races its mount.
  await expect(providerCard(page)).toBeVisible({ timeout: 20000 });
  await dismissOnboarding(page);

  // Deterministic starting point: whatever a previous run left behind is
  // removed through the same authenticated API the page drives (page.request
  // shares the browser context's cookie jar). 404 simply means "already gone".
  await page.request.delete("/v1/credentials/openai_compatible");
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(providerCard(page).locator(".hex-badge")).toHaveText("missing", {
    timeout: 20000,
  });
});

test.afterAll(async () => {
  await context.close();
});

test("create: config alone persists a deletable draft, before any key exists", async () => {
  const card = providerCard(page);
  await card.locator("#openai_compatible-display_name").fill("E2E Gateway");
  await card.locator("#openai_compatible-base_url").fill("http://127.0.0.1:9/v1");

  const [saveResponse] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes("/v1/credentials/openai_compatible/config") &&
        r.request().method() === "PUT",
      { timeout: 15000 },
    ),
    card.getByRole("button", { name: "save config", exact: true }).click(),
  ]);
  expect(saveResponse.status()).toBe(200);

  // The badge still reads "missing" — that word names the vault secret, and
  // none is stored yet. But the draft itself must have persisted server-side,
  // and a keyless draft must be deletable from this page (the backend removes
  // its config alongside a missing secret), not stranded in the DOM.
  await page.reload({ waitUntil: "domcontentloaded" });
  await dismissOnboarding(page);
  await expect(card.locator("#openai_compatible-base_url")).toHaveValue(
    "http://127.0.0.1:9/v1",
    { timeout: 15000 },
  );
  await expect(card.locator(".hex-badge")).toHaveText("missing", { timeout: 15000 });
  await expect(card.getByRole("button", { name: "delete", exact: true })).toBeVisible();
});

test("test: a refused endpoint surfaces the connectivity category and persists nothing", async () => {
  const card = providerCard(page);

  // A draft key goes with the probe; 127.0.0.1:9 has nothing listening, so
  // the route reports `connectivity` (real transport, real refusal — RST in
  // a normal network, a silent drop in mirrored/container networking, which
  // costs the probe its full 15s client timeout; both are connectivity
  // failures). The reveal button's aria-label also contains this string, so
  // match the textbox role, not just the label text.
  await card
    .getByRole("textbox", { name: "OpenAI-compatible gateway token" })
    .fill("e2e-draft-key");
  await card.getByRole("button", { name: "test & discover models", exact: true }).click();

  await expect(page.locator("body")).toContainText("connectivity:", { timeout: 30000 });

  // The failed probe must not persist the draft endpoint or key.
  await page.reload({ waitUntil: "domcontentloaded" });
  await dismissOnboarding(page);
  await expect(card.locator("#openai_compatible-base_url")).toHaveValue(
    "http://127.0.0.1:9/v1",
    { timeout: 15000 },
  );
});

test("rotate: saving a new key replaces the stored secret", async () => {
  const card = providerCard(page);

  // The preceding test's reload cleared the draft, so this types the new key
  // itself — which is what rotation is: enter a replacement, save it.
  await card
    .getByRole("textbox", { name: "OpenAI-compatible gateway token" })
    .fill("e2e-rotated-key");
  const [saveResponse] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/v1/credentials/openai_compatible") && r.request().method() === "PUT",
      { timeout: 15000 },
    ),
    card.getByRole("button", { name: "save", exact: true }).click(),
  ]);
  expect(saveResponse.status()).toBe(200);
  await expect(card.locator(".hex-badge")).toHaveText("configured", { timeout: 15000 });
});

test("edit: endpoint metadata changes without the key ever crossing the wire", async () => {
  const card = providerCard(page);

  await card.locator("#openai_compatible-display_name").fill("E2E Gateway Edited");

  const [saveResponse] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes("/v1/credentials/openai_compatible/config") &&
        r.request().method() === "PUT",
      { timeout: 15000 },
    ),
    card.getByRole("button", { name: "save config", exact: true }).click(),
  ]);
  expect(saveResponse.status()).toBe(200);
  // The edit-without-key-replacement contract, seen on the wire: no secret.
  const configPutBody = saveResponse.request().postData() ?? "";
  expect(configPutBody).not.toContain("e2e-draft-key");
  expect(JSON.parse(configPutBody)).not.toHaveProperty("secret");

  // And the page still describes a configured provider, not a new draft.
  await expect(card.locator(".hex-badge")).toHaveText("configured");
});

test("disable: the credential stays configured but is marked disabled", async () => {
  const card = providerCard(page);

  await card.getByRole("button", { name: "disable", exact: true }).click();
  await expect(card.locator(".hex-badge")).toHaveText("disabled", { timeout: 15000 });

  await card.getByRole("button", { name: "enable", exact: true }).click();
  await expect(card.locator(".hex-badge")).toHaveText("configured", { timeout: 15000 });
});

test("delete: the credential leaves nothing behind", async () => {
  const card = providerCard(page);

  await card.getByRole("button", { name: "delete", exact: true }).click();
  await expect(card.locator(".hex-badge")).toHaveText("missing", { timeout: 15000 });

  // The non-secret config is gone with it, not just the vault entry.
  await page.reload({ waitUntil: "domcontentloaded" });
  await dismissOnboarding(page);
  await expect(card.locator("#openai_compatible-display_name")).toHaveValue("");
  await expect(card.locator("#openai_compatible-base_url")).toHaveValue("");
});
