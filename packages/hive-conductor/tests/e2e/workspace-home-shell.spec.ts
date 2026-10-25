/**
 * Workspace Home shell (#1048 first UI slice).
 *
 * Backend layout/projections/pin already ship; this proves the product surface:
 * `/` lands on `/home`, Home consumes the Home APIs (not Dashboard), Goals
 * section answers honestly when unavailable, and pin posts to the layout
 * authority. Dashboard remains reachable until retirement burn-down.
 */

import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
  });
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

test("index redirects to Workspace Home", async () => {
  await page.goto("/");
  await page.waitForURL("**/home");
  await expect(page.getByRole("heading", { name: "Home", exact: true })).toBeVisible();
  await expect(page.getByTestId("workspace-home")).toBeVisible();
});

test("Home loads layout projections and shows the Goals section honestly", async () => {
  const layout = page.waitForResponse(
    (res) => res.url().includes("/home/layout") && res.request().method() === "GET" && res.ok(),
  );
  const projections = page.waitForResponse(
    (res) =>
      res.url().includes("/home/projections") && res.request().method() === "GET" && res.ok(),
  );
  await page.goto("/home");
  await Promise.all([layout, projections]);
  await expect(page.getByTestId("home-regions")).toBeVisible();
  // #65: Goals project through goal_inspection — empty or listed, not the
  // retired "Goal service unavailable" placeholder.
  const goalsEmpty = page.getByTestId("home-section-goals-empty");
  const goalsUnavailable = page.getByTestId("home-section-goals-unavailable");
  await expect(goalsEmpty.or(goalsUnavailable).or(page.getByRole("heading", { name: "Goals" }))).toBeVisible();
  await expect(goalsUnavailable).toHaveCount(0);
});

test("pinning a Home region posts to the layout pin authority", async () => {
  await page.goto("/home");
  await expect(page.getByTestId("home-regions")).toBeVisible();
  const pinButton = page.getByRole("button", { name: /^Pin Goals$/i });
  await expect(pinButton).toBeVisible();
  const pinResponse = page.waitForResponse(
    (res) =>
      res.url().includes("/home/regions/") &&
      res.url().includes("/pin") &&
      res.request().method() === "POST",
  );
  await pinButton.click();
  const res = await pinResponse;
  expect(res.ok()).toBeTruthy();
  await expect(page.getByRole("button", { name: /^Unpin Goals$/i })).toBeVisible();
});

test("Legacy Dashboard remains reachable from Home", async () => {
  await page.goto("/home");
  await page.getByRole("link", { name: "Legacy Dashboard" }).click();
  await page.waitForURL("**/dashboard");
  await expect(page.getByRole("heading", { name: "Live Operations", exact: true })).toBeVisible();
});
