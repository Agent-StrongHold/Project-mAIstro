import { expect, test, type BrowserContext, type Page, type Route } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

// M7-A12 (#988): opening work in Design Studio must mint canonical objects —
// a Goal revision, a CreativeBrief revision on that revision, a pack binding,
// and one canonical Run — never a product-local DesignRun. These journeys pin
// the mint order, the payload boundaries (pack/width/policy live on the Run,
// never on the Goal), the refresh-restore-from-APIs rule, and the honest
// disabled state when a canonical surface is missing (#286). They also prove
// no model call and no client-side persistence is involved in starting a loop.
test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

// Query-string-tolerant globs: the restore reads append ?goal_id=..., and
// page.unroute() only removes a route registered with the identical pattern.
const PACKS_GLOB = "**/v1/design/packs";
const GOALS_GLOB = "**/v1/goals";
const BRIEFS_GLOB = "**/v1/creative-briefs*";
const RUNS_GLOB = "**/v1/runs*";

const packsListing = [
  {
    pack_id: "product",
    name: "Product",
    summary: "Positioning, launch, and narrative work for a product.",
    execute_backends: ["canvas"],
    artifact_kinds: ["poster", "deck"],
  },
  {
    pack_id: "game",
    name: "Game",
    summary: "Vertical-slice and pitch work for a game.",
    execute_backends: ["canvas"],
    artifact_kinds: ["deck", "cover"],
  },
  {
    pack_id: "book",
    name: "Book",
    summary: "Manuscript, cover, and positioning work for a book.",
    execute_backends: [],
    artifact_kinds: ["cover"],
  },
];

const minted = {
  goal: { goal_id: "goal-loop-1", goal_revision: 1, title: "Launch the field guide" },
  brief: { brief_id: "brief-loop-1", brief_revision: 1, goal_id: "goal-loop-1" },
  run: { run_id: "run-loop-1", goal_id: "goal-loop-1", pack_id: "book", width: 5, policy: "wide" },
};

// Request recorders shared by the mint-order and no-simulation assertions.
let mintOrder: string[];
let goalPostBodies: Record<string, unknown>[];
let runPostBodies: Record<string, unknown>[];
let modelCalls: string[];

function trackMintRequests(target: Page): void {
  mintOrder = [];
  goalPostBodies = [];
  runPostBodies = [];
  modelCalls = [];
  target.on("request", (request) => {
    const url = request.url();
    // Only an invocation can be a model call or a loop mint: the Design Studio
    // page legitimately GETs /v1/design/projects on mount to list persisted
    // projects, and counting that read here would flag the page's own
    // pre-existing listing as a loop-side side effect.
    if (request.method() !== "POST") return;
    if (url.includes("/v1/chat") || url.includes("/v1/design/projects")) modelCalls.push(url);
    if (!url.includes("/v1/goals") && !url.includes("/v1/creative-briefs") && !url.includes("/v1/runs")) return;
    mintOrder.push(url);
    if (url.includes("/v1/goals")) goalPostBodies.push(request.postDataJSON() as Record<string, unknown>);
    if (url.includes("/v1/runs")) runPostBodies.push(request.postDataJSON() as Record<string, unknown>);
  });
}

async function fulfillMint(route: Route, body: unknown): Promise<void> {
  await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(body) });
}

async function stubReadySurfaces(target: Page): Promise<void> {
  await target.route(PACKS_GLOB, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(packsListing) });
  });
  await target.route(GOALS_GLOB, async (route) => {
    if (route.request().method() === "POST") {
      await fulfillMint(route, minted.goal);
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
  });
  await target.route(BRIEFS_GLOB, async (route) => {
    if (route.request().method() === "POST") {
      await fulfillMint(route, minted.brief);
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
  });
  await target.route(RUNS_GLOB, async (route) => {
    if (route.request().method() === "POST") {
      await fulfillMint(route, minted.run);
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
  });
}

async function stubMissingSurfaces(target: Page): Promise<void> {
  for (const path of [PACKS_GLOB, GOALS_GLOB, BRIEFS_GLOB, RUNS_GLOB]) {
    await target.route(path, async (route) => {
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Not Found" }) });
    });
  }
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);
});

test.afterAll(async () => {
  await context.close();
});

test("opening a loop mints Goal, CreativeBrief, then Run — with pack/width/policy on the Run only", async () => {
  trackMintRequests(page);
  await stubReadySurfaces(page);
  await page.goto("/cli/canvas", { waitUntil: "domcontentloaded" });

  // The loop start is the FIRST committed choice: it renders above the
  // visual-mode picker, and starting a book loop never requires touching that
  // picker (it stays available below as the execute-backend choice).
  const loopTitle = page.locator("#loop-start-title");
  const artifactTitle = page.locator("#artifact-types-title");
  await expect(loopTitle).toBeVisible();
  await expect(artifactTitle).toBeVisible();
  const loopBox = await loopTitle.boundingBox();
  const artifactBox = await artifactTitle.boundingBox();
  expect(loopBox?.y ?? Number.NaN).toBeLessThan(artifactBox?.y ?? Number.NaN);

  const packGroup = page.getByRole("group", { name: "Domain pack" });
  await packGroup.getByRole("button").filter({ hasText: "Book" }).click();
  await page.getByLabel("Goal title").fill("Launch the field guide");
  await page.getByLabel("Desired outcome").fill("A launched field guide that sells 1000 copies");
  await page.getByLabel("Stop conditions").fill("Stop when the rubric passes or a person fences the loop");
  await page.getByLabel("Audience").fill("Trail naturalists");
  await page.getByLabel("Constraints").fill("No stock imagery; house type only");
  await page.getByLabel("Creative guidance").fill("Field-journal tone, matte palette");
  await page.getByLabel("Exploration width").fill("5");
  await page.getByLabel("Exploration policy").selectOption("wide");

  // The control is enabled now: every canonical surface reported ready.
  const openLoop = page.getByRole("button", { name: "Open the loop" });
  await expect(openLoop).toBeEnabled();

  // Starting the loop never calls a model (#987) and never creates a
  // Design-Studio project row — the mint is Goal → brief → Run.
  await openLoop.click();
  await expect(page.getByRole("list", { name: "Open loop records" })).toBeVisible();

  expect(mintOrder).toHaveLength(3);
  expect(mintOrder[0]).toContain("/v1/goals");
  expect(mintOrder[1]).toContain("/v1/creative-briefs");
  expect(mintOrder[2]).toContain("/v1/runs");
  expect(modelCalls).toEqual([]);

  // Pack, width, and policy are Run exploration params, not Goal identity.
  expect(goalPostBodies[0]).toEqual({
    title: "Launch the field guide",
    desired_outcome: "A launched field guide that sells 1000 copies",
    stop_conditions: "Stop when the rubric passes or a person fences the loop",
  });
  expect(runPostBodies[0]).toMatchObject({
    goal_id: minted.goal.goal_id,
    goal_revision: minted.goal.goal_revision,
    brief_id: minted.brief.brief_id,
    brief_revision: minted.brief.brief_revision,
    pack_id: "book",
    width: 5,
    policy: "wide",
  });
  expect(runPostBodies[0]).not.toHaveProperty("title");
  expect(runPostBodies[0]).not.toHaveProperty("desired_outcome");

  // The minted records are shown with their canonical ids.
  const records = page.getByRole("list", { name: "Open loop records" });
  await expect(records.getByText(`Goal ${minted.goal.goal_id} · revision ${minted.goal.goal_revision}`, { exact: false })).toBeVisible();
  await expect(records.getByText(`CreativeBrief ${minted.brief.brief_id} · revision ${minted.brief.brief_revision}`, { exact: false })).toBeVisible();
  await expect(records.getByText(`Run ${minted.run.run_id} · pack book · width 5 · policy wide`, { exact: false })).toBeVisible();
});

test("refresh restores the open loop from the APIs, not from client storage", async () => {
  // The mints of the previous journey are now durable server facts: the GET
  // listings return them. Nothing was written to localStorage — the restore
  // can only come from these APIs.
  await page.unroute(GOALS_GLOB);
  await page.route(GOALS_GLOB, async (route) => {
    if (route.request().method() === "POST") {
      await fulfillMint(route, minted.goal);
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([minted.goal]) });
  });
  await page.unroute(BRIEFS_GLOB);
  await page.route(BRIEFS_GLOB, async (route) => {
    if (route.request().method() === "POST") {
      await fulfillMint(route, minted.brief);
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([minted.brief]) });
  });
  await page.unroute(RUNS_GLOB);
  await page.route(RUNS_GLOB, async (route) => {
    if (route.request().method() === "POST") {
      await fulfillMint(route, minted.run);
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([minted.run]) });
  });

  await page.goto("/cli/canvas", { waitUntil: "domcontentloaded" });

  const records = page.getByRole("list", { name: "Open loop records" });
  await expect(records).toBeVisible();
  await expect(records.getByText(`Run ${minted.run.run_id} · pack book · width 5 · policy wide`, { exact: false })).toBeVisible();
  await expect(page.getByText("Loop restored from the canonical records.")).toBeVisible();
});

test("missing Goal/brief surfaces keep the loop start disabled with the honest cause — nothing is simulated", async () => {
  trackMintRequests(page);
  await page.unroute(PACKS_GLOB);
  await page.unroute(GOALS_GLOB);
  await page.unroute(BRIEFS_GLOB);
  await page.unroute(RUNS_GLOB);
  await stubMissingSurfaces(page);

  await page.goto("/cli/canvas", { waitUntil: "domcontentloaded" });

  const availability = page.getByRole("list", { name: "Loop surface availability" });
  await expect(availability.getByText("unavailable")).toHaveCount(4);
  // The cause names the actual missing surface, not a euphemism.
  await expect(availability.getByText(/HTTP 404 from \/v1\/goals/)).toBeVisible();
  await expect(availability.getByText(/HTTP 404 from \/v1\/creative-briefs/)).toBeVisible();

  const openLoop = page.getByRole("button", { name: "Open the loop" });
  await expect(openLoop).toBeDisabled();
  await expect(page.getByLabel("Goal title")).toBeDisabled();
  await expect(page.locator("#loop-start-state")).toContainText("unavailable");
  await expect(page.locator("#loop-start-state")).toContainText("Nothing is simulated");

  // A missing surface is not cured by waiting: no timer fakes the loop (#286).
  await page.waitForTimeout(2500);
  await expect(openLoop).toBeDisabled();
  await expect(availability.getByText("unavailable")).toHaveCount(4);

  // And no mint request was fired while the surfaces were missing.
  expect(mintOrder).toEqual([]);
  expect(modelCalls).toEqual([]);
});
