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

  const generate = page.getByRole("button", { name: "Generate visual" });
  await expect(generate).toBeDisabled();
  await expect(
    page.getByText(/Nothing is submitted or simulated while this control is disabled/),
  ).toBeVisible();
  expect(canvasRequests).toEqual([]);
});
