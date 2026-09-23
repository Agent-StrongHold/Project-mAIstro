/**
 * The Jira draft modal's fields answer to their visible labels, and a
 * required clarifying question exposes that state to assistive technology
 * (#1406).
 *
 * Every field in the clarifying-questions step and the edit step rendered a
 * `<label>` as a sibling of its `<input>`/`<textarea>`, not wrapping it and
 * with no `htmlFor`/`id` pairing -- so the accessible name computed for the
 * control was empty, and a screen reader announced an unlabelled textbox. A
 * required clarifying question's "*" was a literal visual character with no
 * `aria-required`, so "required" was never announced either. The label now
 * wraps its control (the same implicit-association pattern already used by
 * `PersonaWizard.tsx`), and a required clarifying question carries
 * `aria-required="true"`.
 */

import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
const draftReason = `e2e label check ${Date.now()}`;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  page = await context.newPage();
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  const created = await page.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name: `Draft labels ${Date.now()}` },
  });
  expect(created.status()).toBe(201);
  const wsId = (await created.json()).id as string;

  const suggested = await page.request.post(`/v1/work-items/suggest?workspace_id=${wsId}`, {
    data: { work_type: "epic", reason: draftReason },
  });
  expect(suggested.status()).toBe(200);

  await page.addInitScript((id: string) => {
    window.localStorage.setItem("hive_active_workspace_id", id);
  }, wsId);
});

test.afterAll(async () => {
  await context.close();
});

test("a required clarifying question answers to its full visible label and announces required", async () => {
  await page.goto("/work-items", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: new RegExp(`^Epic clarifying ${draftReason}`) }).click();

  // The Epic suggestion always asks for a Jira title first (#1406's fixture
  // in the backend's demo roster); its accessible name must contain the
  // full visible question, not just a fragment or nothing at all.
  const titleField = page.getByRole("textbox", {
    name: "What should the Epic title be in Jira?",
    exact: false,
  });
  await expect(titleField).toBeVisible({ timeout: 15000 });
  await expect(titleField).toHaveAttribute("aria-required", "true");
});

test("the edit step's fields answer to their visible labels", async () => {
  await page
    .getByRole("textbox", { name: "What should the Epic title be in Jira?", exact: false })
    .fill("Test epic");
  await page
    .getByRole("textbox", { name: "Describe the outcome, scope, and definition of done.", exact: false })
    .fill("Outcome");
  await page
    .getByRole("textbox", { name: "Parent Initiative Jira key", exact: false })
    .fill("PROJ-1");
  await page.getByRole("button", { name: "Continue to edit", exact: true }).click();

  await expect(page.getByRole("textbox", { name: "Summary", exact: true })).toBeVisible({
    timeout: 15000,
  });
  await expect(page.getByRole("textbox", { name: "Description", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Project key", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Priority", exact: true })).toBeVisible();
});
