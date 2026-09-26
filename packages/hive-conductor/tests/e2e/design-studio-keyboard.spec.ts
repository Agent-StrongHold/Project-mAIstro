import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

const designSystems = {
  systems: [{ slug: "default", name: "Default", description: "", origin: "bundled" }],
  catalog: { available: true, cause: null, count: 1 },
  ready: true,
  cause: null,
  bundled_count: 1,
};

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });

  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);

  await page.route("**/v1/design/skills", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/v1/design/systems", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(designSystems),
    });
  });
});

test.afterAll(async () => {
  await context.close();
});

test("current Design Studio parent surface is operable by keyboard without enabling fake execution", async () => {
  const canvasRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/v1/canvas/")) canvasRequests.push(request.url());
  });

  await page.goto("/cli/canvas", { waitUntil: "domcontentloaded" });

  const modes = page.getByRole("group", { name: "Design artifact types" });
  const poster = modes.getByRole("button").filter({ hasText: "Poster" });
  const infographic = modes.getByRole("button").filter({ hasText: "Infographic" });

  // Enter the picker using only the real page tab order. This deliberately
  // does not call focus() on a picker control, so removing Poster from the tab
  // order or making the picker pointer-only fails the regression test.
  for (
    let step = 0;
    step < 80 && !(await poster.evaluate((element) => document.activeElement === element));
    step += 1
  ) {
    await page.keyboard.press("Tab");
  }
  await expect(poster).toBeFocused();
  await expect(poster).toHaveAttribute("aria-pressed", "true");

  // Native button order and activation must work without pointer events.
  await page.keyboard.press("Tab");
  await expect(infographic).toBeFocused();
  await page.keyboard.press("Space");
  await expect(infographic).toHaveAttribute("aria-pressed", "true");
  await expect(poster).toHaveAttribute("aria-pressed", "false");

  const prompt = page.getByLabel("Describe the artifact");
  await expect(prompt).toHaveAttribute(
    "placeholder",
    "Describe the infographic you want to create…",
  );

  // Continue with Tab only until the next editable control is reached. This
  // fails if a future artifact-picker change traps focus or adds a pointer-only
  // interaction in the parent surface.
  for (
    let step = 0;
    step < 12 && !(await prompt.evaluate((element) => document.activeElement === element));
    step += 1
  ) {
    await page.keyboard.press("Tab");
  }
  await expect(prompt).toBeFocused();

  // With no brief yet the only editor entry stays disabled; typing the brief
  // is what enables it, entirely through keyboard interaction.
  const openEditor = page.getByRole("button", { name: "Open editor" });
  await expect(openEditor).toBeDisabled();
  await page.keyboard.type("An accessible infographic about canonical Run lineage");
  await expect(prompt).toHaveValue("An accessible infographic about canonical Run lineage");
  await expect(openEditor).toBeEnabled();
  await expect(page.getByText(/draft stays local until a durable project save is connected/)).toBeVisible();
  await expect(page.getByText(/Keyboard: Tab moves between artifact types; Enter or Space selects one/)).toBeVisible();
  await expect(page.getByLabel("Describe the artifact")).toHaveAccessibleDescription(
    /Enter a brief, then open the keyboard-complete editor/,
  );
  expect(canvasRequests).toEqual([]);
});

test("every supported artifact mode is selectable in tab order and announced", async () => {
  await page.goto("/cli/canvas", { waitUntil: "domcontentloaded" });

  const modes = page.getByRole("group", { name: "Design artifact types" });
  const buttons = modes.getByRole("button");
  const names = [
    "Presentation / Deck",
    "Poster",
    "Infographic",
    "Flyer",
    "Social graphic",
    "Card",
    "Cover",
    "Diagram / visual",
    "Custom canvas",
  ];
  await expect(buttons).toHaveCount(names.length);

  // Start from the browser's tab order, then use only keyboard activation for
  // every mode. A pointer click or locator.focus would miss a removed tab stop.
  for (
    let step = 0;
    step < 80 && !(await buttons.nth(0).evaluate((element) => document.activeElement === element));
    step += 1
  ) {
    await page.keyboard.press("Tab");
  }

  for (let index = 0; index < names.length; index += 1) {
    const button = buttons.nth(index);
    await expect(button).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("heading", { name: names[index], exact: true })).toBeVisible();
    await expect(page.getByLabel("Describe the artifact")).toHaveAttribute(
      "placeholder",
      `Describe the ${names[index].toLowerCase()} you want to create…`,
    );
    if (index < names.length - 1) await page.keyboard.press("Tab");
  }

  const results = await new AxeBuilder({ page }).include("main").analyze();
  expect(results.violations).toEqual([]);
});

test("fixed-page and Deck editors expose keyboard workflows and deterministic transitions", async () => {
  await page.goto("/cli/canvas", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Describe the artifact").fill("A keyboard-first poster about reliable execution");
  await page.getByRole("button", { name: "Open editor" }).press("Enter");
  await expect(page.getByRole("heading", { name: "Poster editor" })).toBeFocused();
  await expect(page.getByRole("region", { name: "Poster canvas" })).toBeVisible();
  await page.getByRole("button", { name: "Add layer" }).press("Enter");
  await expect(page.getByRole("option", { name: /Layer 3/ })).toBeVisible();
  await page.getByRole("button", { name: "Move right" }).press("Enter");
  // The shell also renders status regions; scope to the one the editor moved.
  await expect(page.getByRole("status").filter({ hasText: /moved/ })).toBeVisible();
  // The fixed-page editor surface itself is axe-clean, not just the parent page.
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Back to Design Studio" }).press("Enter");
  await expect(page.getByText("What are you making?")).toBeVisible();

  await page.getByRole("button", { name: "Presentation / Deck" }).press("Enter");
  await page.getByLabel("Describe the artifact").fill("A keyboard-first deck about reliable execution");
  await page.getByRole("button", { name: "Open Deck editor" }).press("Enter");
  await expect(page.getByRole("heading", { name: "Deck editor" })).toBeVisible();
  // Deterministic editor entry: the Design Studio page behind the editor
  // unmounts when it opens, so focus must land on a real control inside the
  // Deck editor rather than staying on <body> (the round-13 verification
  // finding: document.activeElement was BODY right after Open Deck editor).
  await expect(page.getByLabel("Deck title")).toBeFocused();
  await page.getByRole("button", { name: "Present" }).press("Enter");
  const embeddedDialog = page.getByRole("dialog");
  await expect(embeddedDialog).toBeVisible();
  // aria-modal containment with a single slide: both slide buttons are
  // disabled, so Tab and Shift+Tab keep focus on the dialog's only enabled
  // control instead of escaping into the app shell behind the overlay (the
  // round-13 finding: five Tabs moved focus out of the dialog).
  await expect(page.getByRole("button", { name: "Exit (Esc)" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Exit (Esc)" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "Exit (Esc)" })).toBeFocused();
  expect(
    await embeddedDialog.evaluate((element) => element.contains(document.activeElement)),
  ).toBe(true);
  // The Deck editor and its presentation dialog are axe-clean surfaces too.
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Exit (Esc)" }).press("Enter");
  await expect(page.getByRole("heading", { name: "Deck editor" })).toBeVisible();
  // Closing the dialog restores focus to the control that opened it.
  await expect(page.getByRole("button", { name: "Present" })).toBeFocused();
});

test("routed /decks surface is keyboard-complete for page navigation, reordering, and presentation", async () => {
  // #769 lifted the M0 containment, so the Deck editor is reachable at its
  // own route. This journey walks the routed surface directly (not the
  // Design-Studio embedded instance) using keyboard-only interaction.
  await page.goto("/decks", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/decks$/);
  await expect(page.getByRole("heading", { name: "Deck editor" })).toBeVisible();
  // The routed surface has the same deterministic entry focus as the
  // embedded editor: focus starts on the Deck title, not <body>.
  await expect(page.getByLabel("Deck title")).toBeFocused();

  // Slide selection must be reachable in the real tab order: Tab from the top
  // of the page until the first ordered-page option is focused, then activate
  // it with Enter like a screen-reader user would.
  const slide1 = page.getByRole("option", { name: "Slide 1" });
  for (
    let step = 0;
    step < 120 && !(await slide1.evaluate((element) => document.activeElement === element));
    step += 1
  ) {
    await page.keyboard.press("Tab");
  }
  await expect(slide1).toBeFocused();
  await expect(slide1).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Slide 1 selected." })).toBeVisible();

  // Ordered-page operations are native buttons, never drag gestures.
  await page.getByRole("button", { name: "+ Add slide" }).press("Enter");
  await expect(page.getByRole("option", { name: "Slide 2" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("status").filter({ hasText: "Slide 2 added and selected." })).toBeVisible();
  await page.getByRole("button", { name: "Move earlier" }).press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Slide moved to position 1." })).toBeVisible();
  await page.getByRole("button", { name: "Move later" }).press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Slide moved to position 2." })).toBeVisible();

  // Presentation opens on the selected page, so select Slide 1 again through
  // the keyboard before presenting.
  await page.getByRole("option", { name: "Slide 1" }).press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Slide 1 selected." })).toBeVisible();

  // The editable slide canvas draws a visible keyboard focus indicator
  // (WCAG 2.4.7, which axe does not scan): focused, its computed outline
  // must be drawn.
  const editor = page.getByRole("textbox", { name: /Edit slide \d+ content/ });
  for (
    let step = 0;
    step < 12 && !(await editor.evaluate((element) => document.activeElement === element));
    step += 1
  ) {
    await page.keyboard.press("Tab");
  }
  await expect(editor).toBeFocused();
  const focusIndicator = await editor.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: Number.parseFloat(style.outlineWidth) };
  });
  expect(focusIndicator.outlineStyle).not.toBe("none");
  expect(focusIndicator.outlineWidth).toBeGreaterThan(0);

  // The routed editor surface is axe-clean, shell included.
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  // Presentation mode: deterministic focus-in, arrow/page-key slide advance
  // with button equivalents, a live position announcement, Escape exit, and
  // focus restored to the control that opened the dialog.
  const present = page.getByRole("button", { name: "Present" });
  await present.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("button", { name: "Exit (Esc)" })).toBeFocused();
  // Tab containment: the aria-modal dialog cycles focus among its own
  // enabled controls (on slide 1 of 2 the Previous button is disabled and
  // skipped, matching browser Tab semantics) and never lets focus escape
  // into the app shell behind the full-screen overlay.
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Next slide" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Exit (Esc)" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Next slide" })).toBeFocused();
  expect(
    await dialog.evaluate((element) => element.contains(document.activeElement)),
  ).toBe(true);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Exit (Esc)" })).toBeFocused();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const position = dialog.getByText(/Slide \d of \d/);
  await expect(position).toHaveText("Slide 1 of 2");
  await page.keyboard.press("ArrowRight");
  await expect(position).toHaveText("Slide 2 of 2");
  await expect(dialog.getByRole("button", { name: "Next slide" })).toBeDisabled();
  await page.keyboard.press("PageDown");
  await expect(position).toHaveText("Slide 2 of 2");
  await page.keyboard.press("ArrowLeft");
  await expect(position).toHaveText("Slide 1 of 2");
  await expect(dialog.getByRole("button", { name: "Previous slide" })).toBeDisabled();
  await page.keyboard.press("PageUp");
  await expect(position).toHaveText("Slide 1 of 2");
  await dialog.getByRole("button", { name: "Next slide" }).press("Enter");
  await expect(position).toHaveText("Slide 2 of 2");
  await dialog.getByRole("button", { name: "Previous slide" }).press("Enter");
  await expect(position).toHaveText("Slide 1 of 2");

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Deck editor" })).toBeVisible();
  await expect(present).toBeFocused();
});
