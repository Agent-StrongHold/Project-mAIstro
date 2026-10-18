/**
 * The Goal → Run → Goal inspection round trip renders canonical truth (#65).
 *
 * `services.goal_inspection` and `services.dag_run_inspection` serve the Goal
 * history and the run detail; `Goals.tsx` and `DagRuns.tsx` are their read-only
 * projection. This spec feeds both pages the exact response shapes those seams
 * serve — same ids, same statuses, no translation — and walks the navigation
 * the product contract asks for:
 *
 *   one Goal, one history (two runs, one failed child, one graph);
 *   a completed run is evidence, never a Goal verdict;
 *   Goal → Run → Goal with the strings each seam served;
 *   waiting-human stays distinguishable from plain failure;
 *   a stale deep link degrades to "Select a goal", not an error.
 *
 * Both doors are stubbed at the network edge, so no Goal, Run or Workspace
 * state is created on the shared test instance — the same rule
 * dag-run-button-truthfulness.spec.ts records for its socket frames.
 */

import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

const WORKSPACE_ID = "ws-goals-e2e";
const GOAL_ID = "goal-alpha-e2e";
const SUBGOAL_ID = "goal-beta-e2e";
const GRAPH_ID = "graph-launch-77";
const RUN_ID = "run-aaa11111";
const CHILD_RUN_ID = "run-bbb22222";
const PAUSED_RUN_ID = "run-ccc33333";

const workspaces = [
  {
    id: WORKSPACE_ID,
    persona_template_id: "pm_fleet",
    name: "Goal round trip",
    theme_id: "default",
    voice_tone_override: null,
    members: [],
    tool_bindings: [],
    active: true,
  },
];

/** One Run row exactly as `_run_evidence_row` serves it: the id and status
 *  copied from the run seam, lineage and Graph identity from the canonical
 *  Run, nothing minted. */
function runRow(overrides: Record<string, unknown>) {
  return {
    run_id: RUN_ID,
    canonical_run_id: RUN_ID,
    status: "completed",
    goal_revision: "3",
    dag_id: "dag-legacy-1",
    started_at: 1000,
    finished_at: 1060,
    error: null,
    parent_run_id: null,
    parent_node_run_id: null,
    actor_principal_id: "pmuser",
    persona_id: null,
    graph_id: GRAPH_ID,
    graph_name: "Launch graph",
    provenance: {},
    ...overrides,
  };
}

const alpha = {
  goal_id: GOAL_ID,
  workspace_id: WORKSPACE_ID,
  project_id: "proj-1",
  // No canonical Goal owner has recorded a verdict: the completed run below
  // must not render as one (ontology invariants 5 and 6).
  goal_state: null,
  goal_state_source: "not_recorded",
  goal_revision_seen: "3",
  goal_revisions: ["2", "3"],
  accountable_agent_id: "agent-prime",
  desired_state: "Launch the site",
  success_condition: "Site is live",
  stop_condition: null,
  success_conditions: ["Site is live"],
  stop_conditions: [],
  parent_goal_id: null,
  execution_disposition: "active",
  blocker: null,
  selected_graphs: [{ graph_id: GRAPH_ID, name: "Launch graph" }],
  unmatched_pipelines: [],
  subgoals: [SUBGOAL_ID],
  run_count: 2,
  runs: [
    runRow({}),
    // A child run delegated by the first — same Goal, ONE history.
    runRow({
      run_id: CHILD_RUN_ID,
      canonical_run_id: CHILD_RUN_ID,
      status: "failed",
      error: "delivery node exhausted attempts",
      parent_run_id: RUN_ID,
      graph_id: null,
      graph_name: null,
    }),
  ],
};

const beta = {
  ...alpha,
  goal_id: SUBGOAL_ID,
  parent_goal_id: GOAL_ID,
  subgoals: [],
  // The HITL fence: a paused run reads waiting-human, not failed.
  execution_disposition: "waiting_human",
  blocker: { run_id: PAUSED_RUN_ID, status: "paused", error: "waiting on approval" },
  run_count: 1,
  runs: [
    runRow({
      run_id: PAUSED_RUN_ID,
      canonical_run_id: PAUSED_RUN_ID,
      status: "paused",
      error: "waiting on approval",
      graph_id: null,
      graph_name: null,
    }),
  ],
};

function runDetail(id: string, withGoalContext: boolean) {
  return {
    id,
    user_id: "pmuser",
    started_at: 1000,
    finished_at: 1060,
    event_count: 0,
    node_states: {},
    events: [],
    node_runs: [
      {
        node_run_id: `nr-${id}`,
        node_id: "launch",
        ordinal: 0,
        status: "completed",
        started_at: 1001,
        finished_at: 1050,
        result: null,
        error: null,
        attempts: [
          {
            attempt_id: `at-${id}`,
            ordinal: 0,
            status: "completed",
            runtime_id: "rt-local-1",
            executor_id: "exec-1",
            started_at: 1001,
            finished_at: 1050,
            result: null,
            error: null,
            cancellation_cause: null,
          },
        ],
      },
    ],
    ...(withGoalContext ? { goal_context: { goal_id: GOAL_ID, goal_revision: "3" } } : {}),
    workspace_id: WORKSPACE_ID,
  };
}

async function stubGoalDoors(p: Page, goals: object[]) {
  await p.route(/\/v1\/workspaces\/[^/]+\/goals(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(goals) });
  });
  // The run detail each Goal row links to: the #1036 seam's exact response.
  await p.route(/\/v1\/dag-runs\/[^/?]+$/, async (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop() ?? "";
    // Only the run this Goal history names carries the recorded Goal context;
    // a run admitted outside any Goal relays no goal_context key at all.
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(runDetail(id, id === RUN_ID)),
    });
  });
  await p.route(/\/v1\/dag-runs(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: RUN_ID, user_id: "pmuser", started_at: 1000, finished_at: 1060, event_count: 0, node_states: {} },
      ]),
    });
  });
  await p.route(/\/v1\/dag-runs\/[^/]+\/events$/, async (route) => {
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: "" });
  });
}

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  await context.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsPM(page);
  await page.route(/\/v1\/workspaces(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(workspaces) });
  });
  await stubGoalDoors(page, [alpha, beta]);
});

test.afterAll(async () => {
  await context.close();
});

async function openGoalFromNav(p: Page) {
  await p.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await p.locator(".icon-sidebar").getByRole("link", { name: "Goals", exact: true }).click();
  await p.waitForURL("**/goals");
  await expect(p.getByRole("heading", { name: "Goals", exact: true })).toBeVisible();
}

test("one Goal with two runs is one history carrying the seam's exact ids", async () => {
  await openGoalFromNav(page);
  // Both goals are listed with their disposition; the parent is one entry
  // with both runs counted, not two pseudo-tasks.
  await expect(page.getByText("goal-alpha-e2e")).toBeVisible();
  const alphaButton = page.getByRole("button", { name: /goal-alpha-e2e/ });
  await expect(alphaButton).toContainText("2");
  await alphaButton.click();
  await expect(page).toHaveURL(new RegExp(`goal=${GOAL_ID}$`));
  // The seam's exact revision, agent and desired state — not a UI-local copy.
  await expect(page.getByText("revision 3")).toBeVisible();
  await expect(page.getByText("agent-prime")).toBeVisible();
  await expect(page.getByText("Launch the site")).toBeVisible();
  await expect(page.getByText("Site is live")).toBeVisible();
  // Both runs of the ONE history, with the run seam's statuses verbatim.
  const runsTable = page.getByRole("table");
  await expect(runsTable).toContainText(RUN_ID);
  await expect(runsTable).toContainText(CHILD_RUN_ID);
  await expect(runsTable).toContainText("completed");
  await expect(runsTable).toContainText("failed");
  await expect(runsTable).toContainText("started by another run");
});

test("a completed run is evidence and never renders the Goal completed", async () => {
  await openGoalFromNav(page);
  await page.getByRole("button", { name: /goal-alpha-e2e/ }).click();
  // The verdict banner names the absent canonical state even though the
  // history's first run completed.
  await expect(page.getByText(/Goal outcome: not recorded/)).toBeVisible();
  await expect(page.getByText(/execution evidence/)).toBeVisible();
});

test("Graph → Run navigation opens the graph's canonical run evidence", async () => {
  await openGoalFromNav(page);
  await page.getByRole("button", { name: /goal-alpha-e2e/ }).click();
  // The Approach card links the selected Graph through the run that carried
  // it — a real Graph → Run path, not a snapshot id posing as a DAG id.
  await page.getByRole("button", { name: new RegExp(GRAPH_ID) }).click();
  await expect(page).toHaveURL(new RegExp(`/dag-runs\\?run=${RUN_ID}$`));
});

test("Goal → Run → Goal round trip keeps the seam's identities", async () => {
  await openGoalFromNav(page);
  await page.getByRole("button", { name: /goal-alpha-e2e/ }).click();
  // Click the completed run's row: the run surface opens on THAT run.
  await page.getByRole("row", { name: new RegExp(RUN_ID) }).click();
  await expect(page).toHaveURL(new RegExp(`/dag-runs\\?run=${RUN_ID}$`));
  // The execution evidence panel is the NodeRun/Attempt tree, verbatim.
  const evidence = page.getByLabel("Canonical execution evidence");
  await expect(evidence).toBeVisible();
  await expect(evidence).toContainText("launch");
  await expect(evidence).toContainText(`nr-${RUN_ID}`);
  await expect(evidence).toContainText(`at-${RUN_ID}`);
  // And the back-link names the Goal context the run itself recorded —
  // exactly the strings the Goal view grouped it under.
  const back = page.getByRole("button", { name: new RegExp(`Goal: ${GOAL_ID}`) });
  await expect(back).toContainText("revision 3");
  await back.click();
  await expect(page).toHaveURL(new RegExp(`/goals\\?goal=${GOAL_ID}&ws=${WORKSPACE_ID}$`));
  await expect(page.getByRole("heading", { name: "Goals", exact: true })).toBeVisible();
  await expect(page.getByText("revision 3")).toBeVisible();
});

test("waiting-human is distinguishable from plain failure", async () => {
  await openGoalFromNav(page);
  await page.getByRole("button", { name: new RegExp(SUBGOAL_ID) }).click();
  await expect(page).toHaveURL(new RegExp(`goal=${SUBGOAL_ID}$`));
  // The subgoal link was the Goal's own delegation lineage; the detail says
  // so and renders the HITL disposition, not a failure badge.
  await expect(page.getByText(new RegExp(`Delegated from.*${GOAL_ID}`, "s"))).toBeVisible();
  await expect(page.getByText("Waiting for you").first()).toBeVisible();
  await expect(page.getByText(/Blocker: run .+ finished as paused/)).toBeVisible();
  await expect(page.getByText("waiting on approval").first()).toBeVisible();
});

test("a run outside any Goal relays no Goal link, and a stale deep link degrades honestly", async () => {
  // The child run's detail carries no goal_context: the run surface must not
  // invent a back-link for it.
  await page.goto(`/dag-runs?run=${CHILD_RUN_ID}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Live DAG Runs", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Goal: / })).toHaveCount(0);
  // A bookmark for a purposed goal lands on the selection prompt — the
  // page's honest empty selection, never an error banner.
  await page.goto(`/goals?goal=goal-never-was&ws=${WORKSPACE_ID}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Select a goal")).toBeVisible();
  await expect(page.getByText("Couldn't load goals.")).toHaveCount(0);
});

test("no recorded work renders the honest empty page", async () => {
  // A second page in the SAME authenticated context, with its own routing
  // stubs: the workspace's Goal door answers empty, exactly as a freshly
  // provisioned Workspace does. The context is already logged in, so no
  // setup/login call belongs here — the login form would never render.
  const fresh = await context.newPage();
  await fresh.route(/\/v1\/workspaces(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(workspaces) });
  });
  await stubGoalDoors(fresh, []);
  await fresh.goto("/goals", { waitUntil: "domcontentloaded" });
  await expect(fresh.getByRole("heading", { name: "Goals", exact: true })).toBeVisible();
  await expect(fresh.getByText("No goals with recorded work yet")).toBeVisible();
  await fresh.close();
});
