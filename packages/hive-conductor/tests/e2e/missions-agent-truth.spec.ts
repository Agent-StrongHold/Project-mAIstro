import { expect, test } from "@playwright/test";

test("mission creation does not offer or submit an unrecorded agent", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("hive_onboarded", "1"));
  const submissions: Record<string, unknown>[] = [];
  const missions: Record<string, unknown>[] = [];
  let agentReads = 0;
  await page.route("**/v1/**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/setup/status", (route) => route.fulfill({ json: { setup_complete: true } }));
  await page.route("**/v1/auth/whoami", (route) => route.fulfill({ json: {
    authenticated: true,
    user: { id: "mission-user", username: "mission-user", role: "user", permissions: [], did: null },
  } }));
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", degraded: false } }));
  await page.route("**/v1/workspaces", (route) => route.fulfill({ json: [{
    id: "workspace-1", name: "My workspace", active: true, members: [], tool_bindings: [],
  }] }));
  await page.route("**/v1/agents", (route) => {
    agentReads += 1;
    return route.fulfill({ json: [{ id: "ghost", name: "Unrecorded agent" }] });
  });
  await page.route("**/v1/tasks?*", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(new URL(route.request().url()).searchParams.get("workspace_id")).toBe("workspace-1");
    const body = route.request().postDataJSON() as Record<string, unknown>;
    submissions.push(body);
    const mission = {
      ...body, id: "new-mission", user_id: "mission-user", status: "pending",
      created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
      progress: 0, steps_total: 0, steps_completed: 0, assigned_agents: [], tags: [], metadata: {},
    };
    missions.push(mission);
    await route.fulfill({ json: mission });
  });
  await page.route("**/v1/tasks", (route) => route.fulfill({ json: missions }));

  await page.goto("/missions");
  await expect(page.getByText("Tasks for this deployment. An agent is shown only when a Run records one.")).toBeVisible();
  await page.getByRole("button", { name: "New Mission +", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "New Mission" });
  const assignment = dialog.getByRole("combobox", { name: "Assign Agent" });
  await expect(assignment).toBeDisabled();
  await expect(assignment).toHaveAccessibleDescription("An agent is shown only when the Run records one. This form does not assign one.");
  await expect(assignment).toHaveValue("");
  await expect(assignment.locator("option")).toHaveCount(1);

  // Native disabled semantics keep the unavailable control out of the tab order.
  await dialog.getByRole("button", { name: "P5", exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).not.toBeVisible();
  expect(submissions).toHaveLength(0);

  await page.getByRole("button", { name: "New Mission +", exact: true }).click();
  await expect(assignment).toBeDisabled();
  await dialog.getByPlaceholder("Mission title").fill("Unassigned work");
  await dialog.getByPlaceholder("What should the mission accomplish?").fill("Wait for a real Run");
  await dialog.getByRole("button", { name: "Create Mission", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(submissions).toEqual([{ name: "Unassigned work", description: "Wait for a real Run", priority: "medium" }]);
  expect(agentReads).toBe(0);
  await expect(page.getByText("Unrecorded agent", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "New Mission +", exact: true }).click();
  await expect(assignment).toBeDisabled();
  await expect(dialog.getByPlaceholder("Mission title")).toHaveValue("");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  expect(submissions).toHaveLength(1);
});
