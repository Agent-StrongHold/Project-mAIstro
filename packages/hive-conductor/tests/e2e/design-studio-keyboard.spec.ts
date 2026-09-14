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
  await page.keyboard.type("An accessible infographic about canonical Run lineage");
  await expect(prompt).toHaveValue("An accessible infographic about canonical Run lineage");

  const openEditor = page.getByRole("button", { name: "Open editor" });
  await expect(openEditor).toBeDisabled();
  await page.getByLabel("Describe the artifact").fill("An accessible infographic about canonical Run lineage");
  await expect(openEditor).toBeEnabled();
  await expect(page.getByText(/draft stays local until a durable project save is connected/)).toBeVisible();
  await expect(page.getByText(/Keyboard: use Tab to move between artifact types/)).toBeVisible();
  await expect(page.getByLabel("Describe the artifact")).toHaveAccessibleDescription(
    /Enter a brief for the selected artifact/,
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
  await expect(page.getByRole("status")).toContainText("moved");
  await page.getByRole("button", { name: "Back to Design Studio" }).press("Enter");
  await expect(page.getByText("What are you making?")).toBeVisible();

  await page.getByRole("button", { name: "Presentation / Deck" }).press("Enter");
  await page.getByLabel("Describe the artifact").fill("A keyboard-first deck about reliable execution");
  await page.getByRole("button", { name: "Open Deck editor" }).press("Enter");
  await expect(page.getByRole("heading", { name: "Deck editor" })).toBeVisible();
  await page.getByRole("button", { name: "Present" }).press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Exit (Esc)" }).press("Enter");
  await expect(page.getByRole("heading", { name: "Deck editor" })).toBeVisible();
});
