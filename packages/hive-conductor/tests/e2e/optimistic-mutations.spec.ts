/**
 * Schedule and Memory-entry mutations patch local state from the mutation's
 * own response instead of refetching the whole collection afterward (#1422).
 *
 * `WorkspaceContext.tsx`'s archive/delete already did this (its own code
 * comment cites #1422); `Schedules.tsx` and `Memory.tsx` still followed
 * every create/update/delete with a GET of the entire collection -- two
 * round trips per action instead of one, and a visible stall on a slow link.
 * Memory is workspace-agnostic; a schedule is created inside a Workspace
 * the caller belongs to (#1201), so the schedule spec makes one first.
 *
 * Memory.tsx's delete and update also apply the change to local state
 * *before* the request resolves and roll it back on failure (#1422): the
 * delete/update specs below hold the request with `page.route` to prove the
 * UI already reflects the change, then fail it and prove the rollback.
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test("toggling a schedule does not refetch the whole collection", async ({ page }) => {
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  const workspace = await page.request.post("/v1/workspaces", {
    data: { persona_template_id: "pm_fleet", name: `Schedules ${Date.now()}` },
  });
  expect(workspace.status()).toBe(201);
  const { id: workspaceId } = (await workspace.json()) as { id: string };

  const created = await page.request.post("/v1/schedules", {
    data: {
      workspace_id: workspaceId,
      name: `Optimistic UI ${Date.now()}`,
      description: "",
      cron_expression: "0 * * * *",
      mission_template_id: "",
      enabled: true,
    },
  });
  expect(created.status()).toBe(201);
  const schedule = (await created.json()) as { id: string; name: string };

  await page.goto("/schedules", { waitUntil: "domcontentloaded" });
  const card = page.locator(".card", { hasText: schedule.name });
  await expect(card).toBeVisible();

  const collectionGets: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "GET" && /\/v1\/schedules$/.test(new URL(r.url()).pathname)) {
      collectionGets.push(r.url());
    }
  });

  const [toggleResponse] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes(`/v1/schedules/${schedule.id}`) && r.request().method() === "PUT",
    ),
    card.locator(".toggle").click(),
  ]);
  expect(toggleResponse.status()).toBe(200);

  // The toggle's own state change is visible immediately from the PUT
  // response -- proof the UI updated without waiting on a second request.
  await expect(card.locator(".toggle.on")).toHaveCount(0);

  // Give a wrongly-added refetch a moment to fire before asserting it didn't.
  await page.waitForTimeout(300);
  expect(collectionGets).toHaveLength(0);
});

test("creating and deleting a memory entry does not refetch the whole collection", async ({
  page,
}) => {
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  await page.goto("/memory", { waitUntil: "domcontentloaded" });
  await page.waitForResponse(
    (r) => /\/v1\/memory\/entries$/.test(new URL(r.url()).pathname) && r.request().method() === "GET",
  );

  const collectionGets: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "GET" && /\/v1\/memory\/entries$/.test(new URL(r.url()).pathname)) {
      collectionGets.push(r.url());
    }
  });

  const key = `optimistic-ui-${Date.now()}`;
  await page.getByRole("button", { name: "+ new" }).click();
  await page.getByPlaceholder("key", { exact: true }).fill(key);
  await page.getByPlaceholder("value", { exact: true }).fill("created without a full refetch");

  const [createResponse] = await Promise.all([
    page.waitForResponse(
      (r) => /\/v1\/memory\/entries$/.test(new URL(r.url()).pathname) && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "save" }).click(),
  ]);
  expect(createResponse.status()).toBe(200);
  const entryCard = page.locator(".card", { hasText: key });
  await expect(entryCard).toBeVisible();

  await entryCard.click();
  await page.getByRole("button", { name: "delete" }).click();
  const [deleteResponse] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/v1/memory/entries/") && r.request().method() === "DELETE",
    ),
    page.getByRole("button", { name: "Confirm" }).click(),
  ]);
  expect(deleteResponse.status()).toBe(204);
  await expect(entryCard).toHaveCount(0);

  await page.waitForTimeout(300);
  expect(collectionGets).toHaveLength(0);
});

test("deleting a memory entry disappears immediately and comes back if the delete fails", async ({
  page,
}) => {
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  const key = `optimistic-delete-${Date.now()}`;
  const created = await page.request.post("/v1/memory/entries", {
    data: { key, value: "will be deleted", namespace: "general", tags: [] },
  });
  expect(created.status()).toBe(200);
  const entry = (await created.json()) as { id: string };

  await page.goto("/memory", { waitUntil: "domcontentloaded" });
  await page.waitForResponse(
    (r) => /\/v1\/memory\/entries$/.test(new URL(r.url()).pathname) && r.request().method() === "GET",
  );

  const card = page.locator(".card", { hasText: key });
  await expect(card).toBeVisible();
  await card.click();

  let releaseDelete: (() => void) | null = null;
  await page.route(`**/v1/memory/entries/${entry.id}`, async (route, request) => {
    if (request.method() !== "DELETE") {
      await route.continue();
      return;
    }
    await new Promise<void>((resolve) => {
      releaseDelete = resolve;
    });
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) });
  });

  await page.getByRole("button", { name: "delete" }).click();
  const deleteResponsePromise = page.waitForResponse(
    (r) => r.url().includes(`/v1/memory/entries/${entry.id}`) && r.request().method() === "DELETE",
  );
  await page.getByRole("button", { name: "Confirm" }).click();

  // The row and its detail panel are gone immediately -- the DELETE is still
  // held by the route handler above, so this can only be the optimistic removal.
  await expect(card).toHaveCount(0);
  await expect(page.getByRole("heading", { name: key })).toHaveCount(0);

  await expect.poll(() => releaseDelete !== null).toBe(true);
  releaseDelete!();
  const deleteResponse = await deleteResponsePromise;
  expect(deleteResponse.status()).toBe(500);

  // The failed delete restores the row.
  await expect(card).toBeVisible();
});

test("editing a memory entry applies immediately and reverts if the save fails", async ({ page }) => {
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  const key = `optimistic-update-${Date.now()}`;
  const created = await page.request.post("/v1/memory/entries", {
    data: { key, value: "original value", namespace: "general", tags: [] },
  });
  expect(created.status()).toBe(200);
  const entry = (await created.json()) as { id: string };

  await page.goto("/memory", { waitUntil: "domcontentloaded" });
  await page.waitForResponse(
    (r) => /\/v1\/memory\/entries$/.test(new URL(r.url()).pathname) && r.request().method() === "GET",
  );

  await page.locator(".card", { hasText: key }).click();
  await page.getByRole("button", { name: "edit" }).click();
  await page.locator("textarea.input-field").fill("edited value");

  let releaseUpdate: (() => void) | null = null;
  await page.route(`**/v1/memory/entries/${entry.id}`, async (route, request) => {
    if (request.method() !== "PUT") {
      await route.continue();
      return;
    }
    await new Promise<void>((resolve) => {
      releaseUpdate = resolve;
    });
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) });
  });

  const putResponsePromise = page.waitForResponse(
    (r) => r.url().includes(`/v1/memory/entries/${entry.id}`) && r.request().method() === "PUT",
  );
  await page.getByRole("button", { name: "save" }).click();

  // The edit form closes and the read-only value updates immediately -- the
  // PUT is still held, so this can only be the optimistic apply. (A bare
  // `getByText("edited value")` would also match the still-open textarea's
  // own value, so the edit form's closing is the real signal here.)
  await expect(page.locator("textarea.input-field")).toHaveCount(0);
  await expect(page.getByText("edited value").first()).toBeVisible();

  await expect.poll(() => releaseUpdate !== null).toBe(true);
  releaseUpdate!();
  const putResponse = await putResponsePromise;
  expect(putResponse.status()).toBe(500);

  // The failed update reverts to the pre-edit value.
  await expect(page.getByText("original value").first()).toBeVisible();
});
