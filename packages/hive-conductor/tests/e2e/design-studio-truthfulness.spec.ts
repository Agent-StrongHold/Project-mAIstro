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
  {
    slug: "infographic",
    name: "Infographic",
    mode: "template",
    description: "Create an infographic.",
    featured: true,
    output_formats: ["svg", "png"],
    tags: ["infographic"],
    discovery_form: [],
    render_slot: "renderer.fixed-page",
  },
  {
    slug: "flyer",
    name: "Flyer",
    mode: "template",
    description: "Create a flyer.",
    featured: false,
    output_formats: ["svg", "png"],
    tags: ["flyer"],
    discovery_form: [],
    render_slot: "renderer.fixed-page",
  },
  {
    slug: "cover",
    name: "Cover",
    mode: "template",
    description: "Create cover art.",
    featured: false,
    output_formats: ["svg", "png"],
    tags: ["cover"],
    discovery_form: [],
    render_slot: "renderer.fixed-page",
  },
  {
    slug: "diagram",
    name: "Diagram",
    mode: "template",
    description: "Create a diagram.",
    featured: false,
    output_formats: ["svg", "png"],
    tags: ["diagram"],
    discovery_form: [],
    render_slot: "renderer.fixed-page",
  },
  {
    slug: "pitch-deck",
    name: "Pitch Deck",
    mode: "deck",
    description: "Create a presentation.",
    featured: true,
    output_formats: ["pptx", "pdf"],
    tags: ["deck"],
    discovery_form: [],
    render_slot: "renderer.deck",
  },
  {
    slug: "web-concept",
    name: "Web Concept",
    mode: "prototype",
    description: "Create a web concept.",
    featured: false,
    output_formats: ["html"],
    tags: ["web"],
    discovery_form: [],
    render_slot: "renderer.reflowable-web",
  },
  {
    slug: "style-board",
    name: "Style Board",
    mode: "design_system",
    description: "Create a style board.",
    featured: false,
    output_formats: ["svg", "png"],
    tags: ["style"],
    discovery_form: [],
    render_slot: "renderer.fixed-page",
  },
  {
    slug: "hero-image",
    name: "Hero Image",
    mode: "image",
    description: "Create hero imagery.",
    featured: true,
    output_formats: ["png"],
    tags: ["image"],
    discovery_form: [],
    render_slot: "renderer.fixed-page",
  },
  {
    slug: "social-card",
    name: "Social Card",
    mode: "template",
    description: "Create a social card.",
    featured: true,
    output_formats: ["png"],
    tags: ["social"],
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

  await expect(page.getByText(/10 design skills and 1 design system available/)).toBeVisible();
  const availableSkills = page.getByLabel("Available design skills");
  await expect(availableSkills.getByText("Hero Image", { exact: true })).toBeVisible();
  await expect(availableSkills.getByText("Social Card", { exact: true })).toBeVisible();

  const discovery = page.getByRole("listitem").filter({ hasText: "Design resource discovery" });
  await expect(discovery).toContainText("available");
  await expect(discovery).toContainText("Brief creation is not connected yet");
  await expect(page.getByText("Brief + design system", { exact: true })).toHaveCount(0);

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

test("Design Studio reports optional design-system catalog degradation without hiding usable resources", async () => {
  await page.unroute("**/v1/design/systems");
  await page.route("**/v1/design/systems", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...designSystems,
        catalog: {
          available: false,
          cause: "Tier-2 design-system catalog could not be loaded",
          count: 0,
        },
      }),
    });
  });

  await page.goto("/cli/canvas", { waitUntil: "domcontentloaded" });

  await expect(page.getByText("degraded", { exact: true })).toBeVisible();
  await expect(page.getByText(/Additional design systems are unavailable: Tier-2 design-system catalog could not be loaded/)).toBeVisible();
  await expect(page.getByLabel("Available design skills").getByText("Social Card", { exact: true })).toBeVisible();

  const discovery = page.getByRole("listitem").filter({ hasText: "Design resource discovery" });
  await expect(discovery).toContainText("degraded");
});
