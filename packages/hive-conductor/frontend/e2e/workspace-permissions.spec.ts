// #336: the archived tab's restore control must reach the same canonical
// elevation affordance as archive. These intercepted tests prove browser
// control wiring, not backend authorization or clean-setup E2E acceptance.
import { expect, test, type Page } from "@playwright/test";

async function archivedWorkspace(page: Page, membershipDenied = false) {
  let elevated = false;
  const patches: unknown[] = [];
  const elevations: { password: string; permissions: string[]; task_id: string }[] = [];
  const workspace = {
    id: "archived-owned", name: "Archived research", persona_template_id: "personal",
    active: false, members: [{ user_id: "daily", role: "owner" }],
    checklist: [], theme_id: "default", tool_bindings: [],
  };
  await page.addInitScript(() => localStorage.setItem("hive_onboarded", "1"));
  // Keep unrelated shell reads inert; every response relevant to restore is
  // registered more specifically below. No backend or real credentials used.
  await page.route("**/v1/**", (route) => route.fulfill({ json: [] }));
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok" } }));
  await page.route("**/v1/setup/status", (route) => route.fulfill({ json: { setup_complete: true } }));
  await page.route("**/v1/auth/whoami", (route) => route.fulfill({ json: {
    authenticated: true,
    user: { id: "daily", username: "daily", role: "user", permissions: ["workspaces.write"] },
  } }));
  await page.route("**/v1/workspaces", (route) => route.fulfill({ json: [workspace] }));
  await page.route("**/v1/workspaces/archived-owned", (route) => {
    expect(route.request().method()).toBe("PATCH");
    patches.push(route.request().postDataJSON());
    if (!elevated) return route.fulfill({ status: 403, json: {
      detail: "Permission 'workspaces.write' required. Elevate to proceed.",
    } });
    if (membershipDenied) return route.fulfill({ status: 403, json: {
      detail: "only an owner can update this workspace",
    } });
    workspace.active = true;
    return route.fulfill({ json: workspace });
  });
  await page.route("**/v1/auth/elevate", (route) => {
    const body = route.request().postDataJSON();
    elevations.push(body);
    if (body.password !== "own-password") return route.fulfill({ status: 401, json: {
      detail: "Invalid password",
    } });
    elevated = true;
    return route.fulfill({ json: { ok: true, task_id: body.task_id, elevated_permissions: body.permissions } });
  });
  await page.goto("/skills");
  await page.getByRole("button", { name: "Archived (1)", exact: true }).click();
  await page.getByRole("button", { name: "Restore Archived research", exact: true }).click();
  return { patches, elevations };
}

async function confirm(page: Page, password = "own-password") {
  const dialog = page.getByRole("dialog", { name: "Permission elevation" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Account password").fill(password);
  await dialog.getByRole("button", { name: "Elevate for this task" }).click();
  return dialog;
}

test("daily owner can elevate and restore through the archived tab", async ({ page }) => {
  const calls = await archivedWorkspace(page);
  await confirm(page);
  await expect(page.getByRole("tab", { name: "Archived research", exact: true })).toHaveAttribute("aria-selected", "true");
  expect(calls.patches).toEqual([{ active: true }, { active: true }]);
  expect(calls.elevations).toEqual([{
    password: "own-password", permissions: ["workspaces.write"], task_id: expect.stringMatching(/^ui-workspaces-write-/),
  }]);
});

test("cancelling elevation does not retry restore and the control can be retried", async ({ page }) => {
  const calls = await archivedWorkspace(page);
  const dialog = page.getByRole("dialog", { name: "Permission elevation" });
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Elevation cancelled for workspaces.write");
  expect(calls.patches).toHaveLength(1);
  expect(calls.elevations).toHaveLength(0);
  await page.getByRole("button", { name: "Restore Archived research", exact: true }).click();
  await confirm(page);
  await expect(page.getByRole("tab", { name: "Archived research", exact: true })).toBeVisible();
});

test("wrong password remains explicit and allows retry without replaying the mutation", async ({ page }) => {
  const calls = await archivedWorkspace(page);
  const dialog = await confirm(page, "wrong-password");
  await expect(dialog).toContainText("Invalid password");
  expect(calls.patches).toHaveLength(1);
  await confirm(page);
  await expect(page.getByRole("tab", { name: "Archived research", exact: true })).toBeVisible();
  expect(calls.elevations).toHaveLength(2);
  expect(calls.patches).toHaveLength(2);
});

test("elevation cannot hide a subsequent membership denial or loop the mutation", async ({ page }) => {
  const calls = await archivedWorkspace(page, true);
  await confirm(page);
  await expect(page.getByRole("alert")).toContainText("only an owner can update this workspace");
  await expect(page.getByRole("dialog", { name: "Permission elevation" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Archived research", exact: true })).toHaveCount(0);
  expect(calls.patches).toHaveLength(2);
  expect(calls.elevations).toHaveLength(1);
});
