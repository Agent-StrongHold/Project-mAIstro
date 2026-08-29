/**
 * The setup wizard and the login form, as one importable session (#371).
 *
 * Both helpers were private to `pm-workflow.spec.ts`. They are the only way
 * into an authenticated page in this harness, and every comment below records
 * a selector that had already gone wrong once — so a second spec that needs a
 * logged-in page has exactly two options: import these, or rediscover the same
 * failures. Moved here verbatim rather than rewritten, for that reason.
 */

import { expect, type Page } from "@playwright/test";

export const ADMIN_USER = "admin";
export const ADMIN_PASS = "adminpass123";
export const PM_USER = "pmuser";
export const PM_PASS = "pmpass1234";

export async function setupIfNeeded(page: Page) {
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
  const conductorName = page.getByLabel("Conductor name", { exact: true });
  await conductorName.waitFor({ state: "visible", timeout: 15000 });

  // 1/5 — Hive
  await conductorName.fill("PM Test Hive");
  await page.locator("button", { hasText: /next/i }).click();

  // 2/5 — Hardware
  await page.locator("text=Beast").first().click();
  await page.locator("button", { hasText: /next/i }).click();

  // 3/5 — Accounts. These are the same credentials loginAsPM() logs in with
  // below, so the accounts this creates are the ones the rest of the suite
  // depends on.
  //
  // Selected by label. This step used to need `nth(0)`/`nth(1)` over
  // `input[type="password"]`, because both password fields had
  // placeholder="password" and nothing else — the very defect #375 fixed, and
  // the reason a test had to identify a credential field by its position in
  // the DOM. Now each one is named, so the selector says which account it is
  // filling in and stops depending on card order.
  await page.getByLabel("Admin username", { exact: true }).fill(ADMIN_USER);
  await page.getByLabel("Admin password", { exact: true }).fill(ADMIN_PASS);
  await page.getByLabel("Daily user username", { exact: true }).fill(PM_USER);
  await page.getByLabel("Daily user password", { exact: true }).fill(PM_PASS);
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
export async function loginAsPM(page: Page) {
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
