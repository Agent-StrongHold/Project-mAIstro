// #292 — the CLI page contract, end to end.
//
// The page is a limited operational console: every command goes to
// POST /v1/cli/exec and the page renders what the backend returns. The
// manifest route (GET /v1/cli/commands) is the machine-readable command set,
// and this suite drives the UI *from* it so a registry entry without e2e
// coverage is impossible to miss. The failure states — unauthorized,
// unsupported, timeout, backend-unavailable — must each answer explicitly;
// the route-intercepted cases pin the page's *rendering* of backend
// failures, never a client-side simulation of success (the established
// pattern in degraded-mode.spec.ts).
import { test, expect } from "./fixtures";

const input = (page: import("@playwright/test").Page) => page.locator("input");

async function runCommand(page: import("@playwright/test").Page, command: string) {
  await input(page).fill(command);
  await input(page).press("Enter");
}

test.describe("CLI page contract (#292)", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("hive_onboarded", "1"));
  });

  test("every shipped command executes through the backend", async ({ page }) => {
    await page.goto("/cli");
    await expect(page.getByText("$ hctl status").first()).toBeVisible({ timeout: 10000 });

    const manifest = await (await page.request.get("/v1/cli/commands")).json();
    const commands: { name: string; summary: string }[] = manifest.commands;
    expect(commands.length).toBeGreaterThanOrEqual(4);

    for (const command of commands) {
      const exec = page.waitForResponse(
        (r) => r.url().includes("/v1/cli/exec") && r.status() === 200,
      );
      await runCommand(page, command.name);
      const response = await exec;
      const body = await response.json();
      expect(body.command, `${command.name} must echo its command`).toBe(command.name);
      expect(
        body.lines.length,
        `${command.name} must produce backend output`,
      ).toBeGreaterThan(0);
      await expect(page.getByText(`$ ${command.name}`).last()).toBeVisible();
      // The page renders what the backend sent — including `help`, whose
      // output lists the manifest itself (no hard-coded client copy).
      if (command.name === "help") {
        for (const listed of commands) {
          await expect(page.getByText(listed.name).last()).toBeVisible();
        }
      }
    }
  });

  test("unsupported command fails explicitly and is not simulated", async ({ page }) => {
    await page.goto("/cli");
    await expect(input(page)).toBeVisible({ timeout: 10000 });

    const refused = page.waitForResponse((r) => r.url().includes("/v1/cli/exec") && r.status() === 404);
    await runCommand(page, "hctl deploy --prod");
    await refused;
    await expect(page.getByText("error: unsupported command")).toBeVisible();
  });

  test("unauthorized execution is reported, never faked", async ({ page }) => {
    await page.route(
      "**/v1/cli/exec",
      (r) => r.fulfill({ status: 401, json: { detail: "Authentication required" } }),
    );
    await page.goto("/cli");
    await expect(input(page)).toBeVisible({ timeout: 10000 });

    await runCommand(page, "help");
    await expect(page.getByText("error: unauthorized — sign in and retry")).toBeVisible();
  });

  test("a backend timeout is reported, never faked", async ({ page }) => {
    await page.route("**/v1/cli/sessions", (r) => r.fulfill({ json: [] }));
    await page.route("**/v1/cli/exec", (r) =>
      r.fulfill({ status: 504, json: { detail: { error: "cli_command_timeout" } } }),
    );
    await page.goto("/cli");
    await expect(input(page)).toBeVisible({ timeout: 10000 });

    await runCommand(page, "hctl status");
    await expect(page.getByText("error: command timed out")).toBeVisible();
  });

  test("a backend outage is reported, never faked", async ({ page }) => {
    await page.route("**/v1/cli/sessions", (r) => r.fulfill({ json: [] }));
    await page.route("**/v1/cli/exec", (r) => r.abort());
    await page.goto("/cli");
    await expect(input(page)).toBeVisible({ timeout: 10000 });

    await runCommand(page, "hctl status");
    await expect(page.getByText("error: could not reach hive-conductor")).toBeVisible();
  });

  test("refresh restores the session's real state", async ({ page }) => {
    await page.goto("/cli");
    await expect(input(page)).toBeVisible({ timeout: 10000 });

    const exec = page.waitForResponse((r) => r.url().includes("/v1/cli/exec") && r.status() === 200);
    await runCommand(page, "hctl agents");
    await exec;
    await expect(page.getByText("$ hctl agents").last()).toBeVisible();

    await page.reload();
    await expect(page.getByText("$ hctl agents").first()).toBeVisible({ timeout: 10000 });
  });
});
