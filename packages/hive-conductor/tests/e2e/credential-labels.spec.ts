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
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  // An explicit context, not `browser.newPage()`: AxeBuilder refuses a page
  // whose context it did not see created.
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
});

test.afterAll(async () => {
  await context.close();
});

/** Each visible field's accessible name, paired with its placeholder. */
async function fields(scope: string) {
  return page.$$eval(`${scope} input`, (inputs) =>
    inputs
      .filter((input) => (input as HTMLInputElement).type !== "hidden")
      .map((input) => {
        const element = input as HTMLInputElement;
        const label = element.labels?.[0]?.textContent?.trim() ?? "";
        return {
          name: element.getAttribute("aria-label") ?? label,
          placeholder: element.placeholder ?? "",
          type: element.type,
        };
      }),
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
      expect(field.name, `a field whose placeholder is "${field.placeholder}"`).not.toBe("");
      // The name may not simply *be* the placeholder: that is the defect, not
      // a fix for it.
      if (field.placeholder) expect(field.name).not.toBe(field.placeholder);
    }
  });

  test("the two password fields on the sign-up form are told apart", async () => {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /^Sign up$/ }).click();

    const secrets = (await fields("form")).filter((field) => field.type === "password");
    const names = secrets.map((field) => field.name);

    expect(names.length).toBe(2);
    expect(new Set(names).size).toBe(2);
  });

  test("a secret field can be revealed, and the control says which field", async () => {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    const password = page.locator('input[autocomplete="current-password"]').first();
    await expect(password).toBeVisible({ timeout: 15000 });

    const toggle = page.getByRole("button", { name: /Password$/ });
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await toggle.click();

    // The reveal is a real type change, which is what actually shows the
    // characters, and `autocomplete` survives it — a field that stopped being
    // a password field would stop being offered a saved credential.
    await expect(password).toHaveAttribute("type", "text");
    await expect(password).toHaveAttribute("autocomplete", "current-password");
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
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

    const unnamed = (await fields("body")).filter((field) => field.name === "");

    expect(unnamed).toEqual([]);
  });
});
