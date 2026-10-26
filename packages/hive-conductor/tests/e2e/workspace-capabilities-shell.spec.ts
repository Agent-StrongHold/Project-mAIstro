/**
 * Capabilities shell (#2273): primary nav lands on the unified surface over
 * `/v1/capabilities`; legacy Agents/MCP/Skills/Topology pages are deleted and
 * their URLs redirect here without reviving those modules.
 */
import { expect, test } from "@playwright/test";
import { loginAsPM, setupIfNeeded } from "./session";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("hive_onboarded", "1");
  });
  await setupIfNeeded(page);
  await loginAsPM(page);
});

test("Capabilities is reachable from the icon rail and loads the API surface", async ({ page }) => {
  await page.goto("/dashboard");
  const link = page.locator(".icon-sidebar").getByRole("link", { name: "Capabilities", exact: true });
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL("**/capabilities");
  await expect(page.getByRole("heading", { name: "Capabilities", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Re-discover providers" })).toBeVisible();
});

test("Capabilities happy path: list slots and re-discover over the public API", async ({ page }) => {
  const listPromise = page.waitForResponse(
    (r) => r.url().includes("/v1/capabilities") && !r.url().includes("discover") && r.request().method() === "GET",
    { timeout: 15000 },
  );
  await page.goto("/capabilities");
  const listRes = await listPromise;
  expect(listRes.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Capabilities", exact: true })).toBeVisible();

  const discoverPromise = page.waitForResponse(
    (r) => r.url().includes("/v1/capabilities/discover") && r.request().method() === "POST",
    { timeout: 15000 },
  );
  await page.getByRole("button", { name: "Re-discover providers" }).click();
  const discoverRes = await discoverPromise;
  expect(discoverRes.ok()).toBeTruthy();
  await expect(page.getByRole("heading", { name: "Capabilities", exact: true })).toBeVisible();
});

test("Agents, Integrations, Skills, and Topology stay out of primary nav", async ({ page }) => {
  await page.goto("/capabilities");
  const rail = page.locator(".icon-sidebar");
  await expect(rail.getByRole("link", { name: "Agents", exact: true })).toHaveCount(0);
  await expect(rail.getByRole("link", { name: "Integrations", exact: true })).toHaveCount(0);
  await expect(rail.getByRole("link", { name: "Skills", exact: true })).toHaveCount(0);
  await expect(rail.getByRole("link", { name: "Topology", exact: true })).toHaveCount(0);
});

test("legacy capability URLs redirect to Capabilities and do not revive deleted modules", async ({
  page,
}) => {
  for (const path of ["/agents", "/mcp", "/skills", "/topology"]) {
    await page.goto(path);
    await page.waitForURL("**/capabilities");
    await expect(page.getByRole("heading", { name: "Capabilities", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "The Hive", exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "MCP", exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Skills", exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Topology", exact: true })).toHaveCount(0);
  }
});
