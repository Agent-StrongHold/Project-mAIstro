// #336: Attention's canonical doors (optimizer proposal accept/reject and the
// HITL answer door) are dags.write protected ops. These intercepted tests
// prove the browser wiring: a 403 from either door must open the same
// canonical elevation affordance as every other advertised mutation, and a
// cancel must not replay the mutation. Route-intercepted; no backend.
import { expect, test, type Page } from "@playwright/test";

const WORKSPACE_ID = "ws-attention-1";
const PROPOSAL_ID = "proposal-7";

async function attentionPage(page: Page) {
  let elevated = false;
  const accepts: unknown[] = [];
  const elevations: { password: string; permissions: string[]; task_id: string }[] = [];
  const workspace = {
    id: WORKSPACE_ID,
    name: "Attention research",
    persona_template_id: "personal",
    active: true,
    members: [{ user_id: "daily", role: "owner" }],
    checklist: [],
    theme_id: "default",
    tool_bindings: [],
  };
  await page.addInitScript(() => localStorage.setItem("hive_onboarded", "1"));
  await page.route("**/v1/**", (route) => route.fulfill({ json: [] }));
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok" } }));
  await page.route("**/v1/setup/status", (route) => route.fulfill({ json: { setup_complete: true } }));
  await page.route("**/v1/auth/whoami", (route) => route.fulfill({ json: {
    authenticated: true,
    user: {
      id: "daily", username: "daily", role: "user",
      permissions: ["dags.write", "workspaces.write"],
    },
  } }));
  await page.route("**/v1/workspaces", (route) => route.fulfill({ json: [workspace] }));
  await page.route(`**/v1/workspaces/${WORKSPACE_ID}/attention`, (route) => route.fulfill({ json: {
    workspace_id: WORKSPACE_ID,
    items: [{
      source_kind: "optimizer_proposal",
      source_id: PROPOSAL_ID,
      workspace_id: WORKSPACE_ID,
      attention_class: "optimizer_proposal",
      rank: 1,
      reason: "pending optimizer proposal",
      evidence: {},
      answer_href: null,
    }],
    summary: { counts_by_class: { optimizer_proposal: 1 }, highest_class: "optimizer_proposal", rising: [], truncated: false },
  } }));
  await page.route(`**/v1/optimizer/proposals/${PROPOSAL_ID}/accept`, (route) => {
    accepts.push(route.request().postDataJSON());
    if (!elevated) {
      return route.fulfill({ status: 403, json: {
        detail: "Permission 'dags.write' required. Elevate to proceed.",
      } });
    }
    return route.fulfill({ json: { apply_outcome: "applied", apply_detail: "topology rewritten" } });
  });
  await page.route("**/v1/auth/elevate", (route) => {
    const body = route.request().postDataJSON();
    elevations.push(body);
    if (body.password !== "own-password") {
      return route.fulfill({ status: 401, json: { detail: "Invalid password" } });
    }
    elevated = true;
    return route.fulfill({ json: { ok: true, task_id: body.task_id, elevated_permissions: body.permissions } });
  });
  await page.goto("/attention");
  await expect(page.getByTestId("attention-items")).toBeVisible();
  return { accepts, elevations };
}

async function confirm(page: Page, password = "own-password") {
  const dialog = page.getByRole("dialog", { name: "Permission elevation" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Account password").fill(password);
  await dialog.getByRole("button", { name: "Elevate for this task" }).click();
  return dialog;
}

test("optimizer decision denied without elevation completes the canonical elevation flow", async ({ page }) => {
  const calls = await attentionPage(page);
  await page.getByTestId("attention-optimizer-accept").click();
  await confirm(page);
  // The post-answer projection refresh unmounts the row, so the durable
  // evidence of the flow is the request trace: deny (403) -> password-backed
  // elevation bound to a task id -> exact replay of the same mutation.
  await expect(page.getByTestId("attention-optimizer-accept")).toBeEnabled({ timeout: 15000 });
  await expect.poll(() => calls.accepts.length, { timeout: 10000 }).toBe(2);
  expect(calls.elevations).toEqual([{
    password: "own-password",
    permissions: ["dags.write"],
    task_id: expect.stringMatching(/^ui-dags-write-/),
  }]);
  await expect(page.getByRole("dialog", { name: "Permission elevation" })).toHaveCount(0);
});

test("cancelling elevation refuses the decision without replaying it and allows retry", async ({ page }) => {
  const calls = await attentionPage(page);
  await page.getByTestId("attention-optimizer-accept").click();
  const dialog = page.getByRole("dialog", { name: "Permission elevation" });
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByTestId("attention-item-error")).toContainText(
    "Elevation cancelled for dags.write",
  );
  expect(calls.accepts).toHaveLength(1);
  expect(calls.elevations).toHaveLength(0);
  await page.getByTestId("attention-optimizer-accept").click();
  await confirm(page);
  await expect(page.getByTestId("attention-optimizer-accept")).toBeEnabled({ timeout: 15000 });
  // Two denied attempts stay visible as two 403s; only the post-elevation
  // replay is a third call. Exactly one password-backed elevation happened.
  await expect.poll(() => calls.accepts.length, { timeout: 10000 }).toBe(3);
  expect(calls.elevations).toHaveLength(1);
});
