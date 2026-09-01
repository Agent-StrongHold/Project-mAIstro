/**
 * Credential fields are named by a label, not by a placeholder (#375).
 *
 * Every password and API-key field in this app took its accessible name from
 * placeholder text. A placeholder is not a name: it disappears the moment the
 * field has a value — so a screen-reader user who tabs back to a half-filled
 * form is told nothing — and it can change with state. The LLM key field read
 * `API key` or `key stored — replace?` depending on the server's answer, so the
 * field's *name* changed under the user; the setup wizard had two fields whose
 * entire name was `password`.
 *
 * `scripts/check-secret-field-labels.py` reads the source and is the cheap
 * ratchet. This asks the browser's own accessibility tree what each field is
 * actually called, which is the only thing that settles it — a label can be
 * present, associated with the wrong control, and score perfectly on a source
 * scan.
 */

import AxeBuilder from "@axe-core/playwright";
import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { ADMIN_PASS, ADMIN_USER, loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let policyContext: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  const baseURL = test.info().project.use.baseURL;

  // Provisioning may establish an authenticated browser session as part of the
  // first-run flow. Do it in a disposable context so the page whose login form
  // we inspect starts genuinely anonymous instead of being redirected away
  // from /login by a setup-created session cookie.
  const setupContext = await browser.newContext({ baseURL });
  const setupPage = await setupContext.newPage();
  await setupIfNeeded(setupPage);
  await setupContext.close();

  // An explicit fresh context, not `browser.newPage()`: AxeBuilder refuses a
  // page whose context it did not see created, and the clean context is also
  // the isolation boundary for the anonymous login accessibility assertions.
  context = await browser.newContext({ baseURL });
  page = await context.newPage();

  // #313 correctly closes ordinary registration after setup. This spec is
  // about the accessibility semantics of the sign-up form, so establish the
  // precondition through the real admin policy API in a separate context. Do
  // not share its admin cookie with the page whose login behavior we inspect.
  policyContext = await browser.newContext({ baseURL });
  const login = await policyContext.request.post("/v1/auth/login", {
    data: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  expect(login.status()).toBe(200);
  const opened = await policyContext.request.put("/v1/settings/registration-policy", {
    data: { mode: "open" },
  });
  expect(opened.status()).toBe(200);
});

test.afterAll(async () => {
  // Restore the product default so this accessibility fixture cannot alter
  // registration semantics for another e2e spec sharing the same server.
  const closed = await policyContext.request.put("/v1/settings/registration-policy", {
    data: { mode: "closed" },
  });
  expect(closed.status()).toBe(200);
  await policyContext.close();
  await context.close();
});

/**
 * The visible fields in `scope`, with the placeholder each one carries.
 *
 * The *name* is deliberately not computed here. An earlier version read
 * `aria-label` or the first associated `<label>`, which approximates the
 * accessible-name algorithm and gets it wrong for a field named through
 * `aria-labelledby` — a form the source gate explicitly permits, so the two
 * halves of this issue's evidence disagreed with each other (raised in
 * review). The assertions below ask Playwright for the browser's computed
 * name instead.
 */
async function fields(scope: string) {
  return page.$$eval(`${scope} input`, (inputs) =>
    inputs
      .filter((input) => (input as HTMLInputElement).type !== "hidden")
      .map((input, index) => ({
        index,
        placeholder: (input as HTMLInputElement).placeholder ?? "",
        type: (input as HTMLInputElement).type,
      })),
  );
}

test.describe("Credential fields carry persistent labels", () => {
  test("every field on the sign-in form is named, and not by its placeholder", async () => {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await expect(page.locator('input[autocomplete="username"]').first()).toBeVisible({
      timeout: 15000,
    });

    const found = await fields("form");
    expect(found.length).toBeGreaterThanOrEqual(2);

    for (const field of found) {
      const input = page.locator("form input").nth(field.index);
      // The browser's computed name, not an approximation of it.
      await expect(input).not.toHaveAccessibleName("");
      // And the name may not simply *be* the placeholder: that is the defect,
      // not a fix for it.
      if (field.placeholder) await expect(input).not.toHaveAccessibleName(field.placeholder);
    }
  });

  test("the two password fields on the sign-up form are told apart", async () => {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /^Sign up$/ }).click();

    const secrets = page.locator('form input[type="password"]');
    await expect(secrets).toHaveCount(2);

    // Distinct computed names. Both fields were called "password" and nothing
    // else before this change.
    await expect(secrets.nth(0)).toHaveAccessibleName("Password");
    await expect(secrets.nth(1)).toHaveAccessibleName("Confirm password");
  });

  test("a secret field can be revealed, and the control says which field", async () => {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    const password = page.locator('input[autocomplete="current-password"]').first();
    await expect(password).toBeVisible({ timeout: 15000 });

    const toggle = page.getByRole("button", { name: "Show Password" });
    await toggle.click();

    // The reveal is a real type change, which is what actually shows the
    // characters, and `autocomplete` survives it — a field that stopped being
    // a password field would stop being offered a saved credential.
    await expect(password).toHaveAttribute("type", "text");
    await expect(password).toHaveAttribute("autocomplete", "current-password");
    // The action name follows the state, and names its own field: a page with
    // several secret fields otherwise has several buttons all called "Show".
    await expect(page.getByRole("button", { name: "Hide Password" })).toBeVisible();
  });

  test("switching between sign in and sign up does not expose a revealed password", async () => {
    // The form preserves `password` across the switch, and React reuses a
    // component at the same child position — so without a `key` per form, a
    // password revealed on one form is still revealed, and still filled, on
    // the other. The user never asked to show it there (raised in review).
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    const password = page.locator('input[autocomplete="current-password"]').first();
    await expect(password).toBeVisible({ timeout: 15000 });
    await password.fill("hunter2");
    await page.getByRole("button", { name: "Show Password" }).click();
    await expect(password).toHaveAttribute("type", "text");

    await page.getByRole("button", { name: /^Sign up$/ }).click();

    const after = page.locator('input[autocomplete="new-password"]').first();
    await expect(after).toBeVisible();
    await expect(after).toHaveAttribute("type", "password");
  });

  test("axe finds no violation on the sign-in form", async () => {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await expect(page.locator("form").first()).toBeVisible({ timeout: 15000 });

    // `color-contrast` excluded and only that: the findings are palette
    // decisions belonging to #376's contrast floors. Every naming rule runs.
    const results = await new AxeBuilder({ page })
      .include("form")
      .disableRules(["color-contrast"])
      .analyze();

    expect(results.violations).toEqual([]);
  });

  test("every field on the credentials page is named too", async () => {
    // Behind authentication, and the surface where the placeholder changed
    // with server state.
    await loginAsPM(page);
    await page.goto("/credentials", { waitUntil: "domcontentloaded" });
    await expect(page.locator("input").first()).toBeVisible({ timeout: 15000 });

    const found = await fields("body");
    expect(found.length).toBeGreaterThan(0);

    for (const field of found) {
      await expect(page.locator("body input").nth(field.index)).not.toHaveAccessibleName("");
    }
  });
});
