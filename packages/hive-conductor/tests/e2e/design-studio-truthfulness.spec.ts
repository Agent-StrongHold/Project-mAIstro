import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

const designSkills = [
  {
    slug: "brand-poster",
    name: "Brand Poster",
    mode: "template",
    description: "Create a fixed-page branded poster.",
    featured: true,
    output_formats: ["svg", "png"],
    tags: ["poster"],
    discovery_form: [],
    render_slot: "renderer.fixed-page",
  },
];

const designSystems = {
  systems: [{ slug: "default", name: "Default", description: "", origin: "bundled" }],
  catalog: { available: true, cause: null, count: 1 },
  ready: true,
  cause: null,
  bundled_count: 1,
};

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });

  // These tests exercise the post-onboarding Design Studio product surface,
  // not the onboarding journey itself. Seed the same durable browser fact the
  // real "Skip onboarding" / "Get Started" actions write, before React mounts,
  // so the modal cannot obscure controls and the tests do not bypass it with
  // force-clicks.
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });

  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);

  await page.route("**/v1/design/skills", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(designSkills) });
  });
  await page.route("**/v1/design/systems", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(designSystems) });
  });
});

test.afterAll(async () => {
  await context.close();
});

test("Design Studio is the parent surface and never enables fake visual execution", async () => {
  const canvasRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/v1/canvas/")) canvasRequests.push(request.url());
  });

  await page.goto("/cli/canvas", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Design Studio", { exact: true })).toBeVisible();

  const artifactTypes = page.getByRole("group", { name: "Design artifact types" });
  for (const mode of [
    "Presentation / Deck",
    "Poster",
    "Infographic",
    "Flyer",
    "Social graphic",
    "Card",
    "Cover",
    "Diagram / visual",
    "Custom canvas",
  ]) {
    await expect(artifactTypes.getByRole("button").filter({ hasText: mode })).toBeVisible();
  }

  await expect(page.getByText(/1 design skill and 1 design system available/)).toBeVisible();

  const generate = page.getByRole("button", { name: "Generate visual" });
  await expect(generate).toBeDisabled();
  await page.getByLabel("Describe the artifact").fill("An infographic explaining durable Run lineage");
  await expect(generate).toBeDisabled();

  // The old implementation changed stages to running/done solely because time
  // elapsed and then called /v1/canvas/eval. Waiting must not manufacture work.
  await page.waitForTimeout(1200);
  await expect(page.getByText("Running...", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Generated output for/)).toHaveCount(0);
  expect(canvasRequests).toEqual([]);

  // Engineering coordination belongs in issues/docs, not the shipped product.
  const product = page.locator("body");
  await expect(product).not.toContainText("#735");
  await expect(product).not.toContainText("#752");
  await expect(product).not.toContainText("M3 #");
});

test("Deck is a contained Design Studio mode, not a route escape", async () => {
  await page.goto("/cli/canvas", { waitUntil: "domcontentloaded" });
  const artifactTypes = page.getByRole("group", { name: "Design artifact types" });
  await artifactTypes.getByRole("button").filter({ hasText: "Presentation / Deck" }).click();

  await expect(page.getByRole("button", { name: "Open Deck editor" })).toBeDisabled();
  await expect(page.getByText(/Deck editing is temporarily unavailable while secure rendering is enabled/)).toBeVisible();
  await expect(page).toHaveURL(/\/cli\/canvas$/);
});
