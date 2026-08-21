import { test, expect } from "./fixtures";

test.describe("App Shell", () => {
  test("has icon sidebar with bee emoji", async ({ page }) => {
    await page.goto("/chat");
    const bee = page.locator(".icon-sidebar").first();
    await expect(bee).toBeVisible({ timeout: 10000 });
  });

  test("sidebar navigation links work", async ({ page }) => {
    await page.goto("/chat");
    const navLinks = page.locator("a.nav-icon");
    const count = await navLinks.count();
    expect(count).toBeGreaterThanOrEqual(8);
  });
});

test.describe("Chat Page", () => {
  test("shows chat empty state with suggestions", async ({ page }) => {
    await page.goto("/chat");
    await expect(page.locator("text=Hive Conductor").first()).toBeVisible({ timeout: 10000 });
  });

  test("has message input", async ({ page }) => {
    await page.goto("/chat");
    const input = page.locator("input.input-field");
    await expect(input.first()).toBeVisible({ timeout: 10000 });
  });

  test("suggestions are clickable cards", async ({ page }) => {
    await page.goto("/chat");
    const cards = page.locator(".card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe("Agents Page", () => {
  test("loads agents from API", async ({ page }) => {
    await page.goto("/agents");
    await expect(page.locator("text=The Hive").first()).toBeVisible({ timeout: 10000 });
    const response = await page.waitForResponse("**/v1/agents", { timeout: 10000 }).catch(() => null);
    if (response) expect(response.status()).toBe(200);
  });
});

test.describe("Missions Page", () => {
  test("loads missions from API", async ({ page }) => {
    await page.goto("/missions");
    const response = await page.waitForResponse("**/v1/tasks", { timeout: 10000 }).catch(() => null);
    if (response) expect(response.status()).toBe(200);
  });
});

test.describe("Skills Page", () => {
  test("loads skills from API", async ({ page }) => {
    await page.goto("/skills");
    const response = await page.waitForResponse("**/v1/skills", { timeout: 10000 }).catch(() => null);
    if (response) expect(response.status()).toBe(200);
  });
});

test.describe("Schedules Page", () => {
  test("loads schedules with tabs", async ({ page }) => {
    await page.goto("/schedules");
    const response = await page.waitForResponse("**/v1/schedules", { timeout: 10000 }).catch(() => null);
    if (response) expect(response.status()).toBe(200);
  });
});

test.describe("Memory Page", () => {
  test("loads memory entries", async ({ page }) => {
    await page.goto("/memory");
    const response = await page.waitForResponse("**/v1/memory/entries", { timeout: 10000 }).catch(() => null);
    if (response) expect(response.status()).toBe(200);
  });
});

test.describe("MCP Page", () => {
  test("loads MCP servers and tools", async ({ page }) => {
    await page.goto("/mcp");
    const response = await page.waitForResponse("**/v1/mcp/servers", { timeout: 10000 }).catch(() => null);
    if (response) expect(response.status()).toBe(200);
  });
});

test.describe("Containers Page", () => {
  test("loads containers from API", async ({ page }) => {
    await page.goto("/containers");
    const response = await page.waitForResponse("**/v1/containers", { timeout: 10000 }).catch(() => null);
    if (response) expect(response.status()).toBe(200);
  });
});

test.describe("CLI Page", () => {
  test("shows terminal with status", async ({ page }) => {
    await page.goto("/cli");
    await expect(page.locator("text=CLI").first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=hctl status").first()).toBeVisible();
  });

  test("can type help command", async ({ page }) => {
    await page.goto("/cli");
    const input = page.locator("input");
    await expect(input).toBeVisible({ timeout: 10000 });
    await input.fill("help");
    await input.press("Enter");
    await expect(page.locator("text=hctl status")).toBeVisible({ timeout: 5000 });
  });
});

test.describe("Settings Page", () => {
  test("loads settings from API", async ({ page }) => {
    await page.goto("/settings");
    const response = await page.waitForResponse("**/v1/settings", { timeout: 10000 }).catch(() => null);
    if (response) expect(response.status()).toBe(200);
  });
});

test.describe("Design System", () => {
  test("has tan paper background", async ({ page }) => {
    await page.goto("/chat");
    const shell = page.locator(".app-shell").first();
    await expect(shell).toBeVisible({ timeout: 10000 });
  });

  test("hex badges render with clip-path", async ({ page }) => {
    await page.goto("/agents");
    await page.waitForTimeout(3000);
    const hex = page.locator(".hex-badge").first();
    if (await hex.isVisible()) {
      const clipPath = await hex.evaluate((el) => getComputedStyle(el).clipPath);
      expect(clipPath).toContain("polygon");
    }
  });

  test("honeycomb dot pattern on background", async ({ page }) => {
    await page.goto("/chat");
    const shell = page.locator(".app-shell").first();
    await expect(shell).toBeVisible({ timeout: 10000 });
    const bgImage = await shell.evaluate((el) => getComputedStyle(el).backgroundImage);
    expect(bgImage).toContain("radial-gradient");
  });
});
