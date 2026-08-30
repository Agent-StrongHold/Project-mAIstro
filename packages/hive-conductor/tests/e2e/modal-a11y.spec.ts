/**
 * Dialog semantics for the shared Modal (#371).
 *
 * These run in a real browser rather than in jsdom, and for this component
 * that is the stronger evidence, not the weaker: every property under test —
 * the focus trap, the inert background, the top layer, focus restoration — is
 * something `showModal()` asks the *browser* to do. A jsdom suite would be
 * asserting against a stub of the exact behaviour in question.
 *
 * The Create Agent dialog stands in for all of them. That is the point of one
 * shared component: a consumer cannot have its own semantics, so proving one
 * proves the set. These use only what every dialog has — a title, a close
 * button, a backdrop.
 */

import AxeBuilder from "@axe-core/playwright";
import { test, expect, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

// Serial, with one signed-in page for the whole file. Setup and login cost
// roughly as much as everything else here put together, and six repeats of
// them would spend most of this suite's CI budget proving the login form works
// -- which `pm-workflow.spec.ts` already does.
test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  // An explicit context, not `browser.newPage()`: AxeBuilder refuses a page
  // whose context it did not see created, because it injects the analysis into
  // every frame and needs the context to do it.
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);
  // The onboarding tour is itself a dialog and covers the whole app on a fresh
  // install. Marking it seen before the page scripts run keeps this spec about
  // one dialog rather than about whichever one happens to be on top.
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));
});

test.afterAll(async () => {
  await context.close();
});

async function openCreateAgent(): Promise<Locator> {
  // `domcontentloaded`, not the default `load`: /agents holds a long-lived
  // connection open, so the load event can be a long time coming and has
  // nothing to do with the page being interactive.
  await page.goto("/agents", { waitUntil: "domcontentloaded" });

  const create = page.getByRole("button", { name: /\+ Create/ }).first();
  await expect(create).toBeVisible({ timeout: 15000 });
  await create.focus();
  await create.click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 10000 });
  return dialog;
}

const focusIsInsideTheDialog = () =>
  page.evaluate(() => {
    const dialog = document.querySelector("dialog[open]");
    return !!dialog && !!document.activeElement && dialog.contains(document.activeElement);
  });

test.describe("Shared modal dialog semantics", () => {
  test("it is a dialog, and its accessible name is its title", async () => {
    // The previous implementation was two anonymous <div>s: assistive
    // technology saw containers appear with nothing to announce.
    const dialog = await openCreateAgent();

    // `:modal` is true for exactly the dialogs `showModal()` opened — the
    // top-layer, background-inert ones. Asserting it rather than an
    // `aria-modal` attribute is deliberate: on a native <dialog> the platform
    // supplies the modal semantics, and authoring `aria-modal` there is
    // discouraged, so the attribute's absence is the correct state.
    const modal = await page.evaluate(
      () => document.querySelector("dialog[open]")?.matches(":modal") ?? false,
    );

    expect(modal).toBe(true);
    await expect(dialog).toHaveAccessibleName("Create Agent");
  });

  test("focus moves into the dialog and cannot leave it by keyboard", async () => {
    const dialog = await openCreateAgent();

    expect(await focusIsInsideTheDialog()).toBe(true);

    // Enough presses to walk past every control in the dialog and wrap. Without
    // a trap, focus would be out in the page behind long before the last one.
    for (let i = 0; i < 30; i += 1) await page.keyboard.press("Tab");
    expect(await focusIsInsideTheDialog()).toBe(true);

    for (let i = 0; i < 8; i += 1) await page.keyboard.press("Shift+Tab");
    expect(await focusIsInsideTheDialog()).toBe(true);
    await expect(dialog).toBeVisible();
  });

  test("no control behind the dialog can be focused at all", async () => {
    await openCreateAgent();

    // Not "nothing outside is focused" but "nothing outside is focusABLE" —
    // the tab-order half of this issue's definition of done. Asking each
    // control to take focus and seeing whether it does is what an inert
    // subtree actually guarantees.
    const reachable = await page.evaluate(() => {
      const dialog = document.querySelector("dialog[open]");
      const outside = Array.from(
        document.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea"),
      ).filter((element) => !dialog?.contains(element));
      for (const element of outside) {
        element.focus();
        if (document.activeElement === element) return element.tagName;
      }
      return null;
    });

    expect(reachable).toBeNull();
  });

  test("Escape closes it and focus returns to the control that opened it", async () => {
    const dialog = await openCreateAgent();

    await page.keyboard.press("Escape");

    await expect(dialog).toBeHidden();
    // Focus stranded on <body> is the failure a keyboard user feels: the next
    // Tab starts again at the top of the page instead of where they were.
    const restored = await page.evaluate(() => document.activeElement?.textContent?.trim());
    expect(restored).toContain("Create");
  });

  test("the close button closes it, and says what it closes", async () => {
    const dialog = await openCreateAgent();

    await page.getByRole("button", { name: "Close Create Agent" }).click();

    await expect(dialog).toBeHidden();
  });

  test("axe finds no violation in the open dialog", async () => {
    await openCreateAgent();

    // `color-contrast` is excluded, and only that: the two contrast findings in
    // this dialog are a green radio label and the panel's own surface, which
    // are palette decisions belonging to #376's typography and contrast floors.
    // Every other rule runs, including the naming rules this issue is about —
    // the scan reported the Model <select> as nameless and that is fixed here
    // rather than suppressed.
    const results = await new AxeBuilder({ page })
      .include("dialog[open]")
      .disableRules(["color-contrast"])
      .analyze();

    expect(results.violations).toEqual([]);
  });
});
