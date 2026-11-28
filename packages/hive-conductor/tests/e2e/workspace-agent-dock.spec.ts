/**
 * Persistent Workspace Agent shell surface (#2549).
 *
 * AC-3: the persistent Workspace Agent is a shell-level surface — mounted
 * once in AppShell, present on every page, not a Chat-page-only feature.
 * AC-1: first-run onboarding copy describes the persistent-agent-first
 * product and carries zero PM-demo heritage (no project management / PM /
 * Jira / Confluence anywhere in the tour).
 * AC-2: the standard workspace-creation dialog offers no PM Fleet preset.
 */
import { expect, test, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

// Every page the acceptance criteria name. The launcher must be visible on
// each without any per-page wiring — it lives in the shell.
const EVERY_PAGE = [
  "/home",
  "/chat",
  "/goals",
  "/attention",
  "/approvals",
  "/design-studio",
  "/dags",
  "/dag-runs",
  "/missions",
  "/backlog",
  "/capabilities",
  "/quotas",
  "/knowledge",
  "/cli",
  "/credentials",
  "/audit",
  "/settings",
];

async function loginSeeded(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  await setupIfNeeded(page);
  await loginAsPM(page);
}

test.describe("persistent Workspace Agent shell surface (#2549 AC-3)", () => {
  test.beforeEach(async ({ page }) => {
    await loginSeeded(page);
  });

  test("the launcher is present on every page", async ({ page }) => {
    for (const path of EVERY_PAGE) {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      const launcher = page.getByTestId("workspace-agent-launcher");
      await expect(launcher, `launcher visible on ${path}`).toBeVisible();
    }
  });

  test("the dock opens one conversation surface with a composer", async ({ page }) => {
    await page.goto("/goals", { waitUntil: "domcontentloaded" });
    await page.getByTestId("workspace-agent-launcher").click();
    const panel = page.getByTestId("workspace-agent-dock");
    await expect(panel).toBeVisible();
    // Exactly one persistent agent instance in the shell.
    expect(await page.getByTestId("workspace-agent-dock-root").count()).toBe(1);
    await expect(panel.getByRole("log", { name: "Workspace Agent messages" })).toBeVisible();
    await expect(panel.getByLabel("Message the Workspace Agent")).toBeVisible();
    // Escape closes and focus returns to the launcher (keyboard journey).
    await page.keyboard.press("Escape");
    await expect(panel).not.toBeVisible();
    await expect(page.getByTestId("workspace-agent-launcher")).toBeFocused();
  });

  test("the dock survives client-side navigation between pages", async ({ page }) => {
    await page.goto("/home", { waitUntil: "domcontentloaded" });
    await page.getByTestId("workspace-agent-launcher").click();
    await expect(page.getByTestId("workspace-agent-dock")).toBeVisible();
    // SPA navigation (no full reload): the shell persists, so the dock must too.
    await page
      .locator(".icon-sidebar")
      .getByRole("link", { name: "Settings", exact: true })
      .click();
    await page.waitForURL("**/settings");
    await expect(page.getByTestId("workspace-agent-launcher")).toBeVisible();
    await expect(page.getByTestId("workspace-agent-dock")).toBeVisible();
  });
});

test.describe("first-run copy carries no PM-demo heritage (#2549 AC-1)", () => {
  test.beforeEach(async ({ page }) => {
    await setupIfNeeded(page);
    await loginAsPM(page);
    // Deliberately no `hive_onboarded`: the first authenticated visit shows
    // the onboarding tour.
  });

  test("onboarding names the persistent agent and never mentions PM/Jira/Confluence", async ({
    page,
  }) => {
    await page.goto("/home", { waitUntil: "domcontentloaded" });
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 15000 });
    const banned = /project\s*management|\bPM\b|jira|confluence/i;
    // Four steps; each must be free of PM-demo heritage, and the tour must
    // lead with the persistent Workspace Agent, not a project-management
    // assistant framing.
    for (let step = 0; step < 4; step++) {
      const text = await dialog.innerText();
      expect(text, `onboarding step ${step + 1} copy`).not.toMatch(banned);
      if (step === 0) {
        expect(text).toMatch(/Workspace Agent/i);
      }
      if (step < 3) {
        await dialog.getByRole("button", { name: /^Next$/ }).click();
      }
    }
  });
});

test.describe("workspace dialog offers no PM Fleet preset (#2549 AC-2)", () => {
  test.beforeEach(async ({ page }) => {
    await loginSeeded(page);
  });

  test("persona picker lists no PM Fleet / Jira preset", async ({ page }) => {
    await page.goto("/home", { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "New workspace", exact: true }).click();
    const picker = page.locator(".workspace-persona-picker");
    await expect(picker).toBeVisible({ timeout: 15000 });
    // The picker read resolves (skeleton or "no personas" would both fail
    // the option scan below for the wrong reason), then no option carries
    // the PM-demo preset.
    await expect
      .poll(async () => picker.locator(".workspace-persona-option").count(), {
        timeout: 15000,
      })
      .toBeGreaterThan(0);
    const optionText = await picker.locator(".workspace-persona-option").allInnerTexts();
    for (const text of optionText) {
      expect(text, `persona option "${text}"`).not.toMatch(/PM Fleet|Jira|Confluence/i);
    }
  });
});
