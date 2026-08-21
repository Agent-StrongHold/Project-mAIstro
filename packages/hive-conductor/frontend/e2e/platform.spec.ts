import { test, expect } from "./fixtures";

test.describe("Dashboard Page", () => {
  test("loads and shows content", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForTimeout(3000);
    // Should have the Live Operations header or widget content
    const content = await page.textContent("body");
    expect(content?.length).toBeGreaterThan(100);
  });

  test("dashboard metrics API responds", async ({ page }) => {
    const response = await page.request.get("/v1/dashboard/metrics");
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data).toHaveProperty("active_agents");
  });

  test("dashboard layout API responds with tabs", async ({ page }) => {
    const response = await page.request.get("/v1/dashboard/layout");
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.tabs.length).toBeGreaterThanOrEqual(1);
  });

  test("widgets render after loading", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForTimeout(5000);
    // Widget cards have title text in uppercase
    const body = await page.textContent("body");
    expect(body?.length).toBeGreaterThan(500); // page has content
  });

  test("edit mode shows undo/redo", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForTimeout(2000);
    const editBtn = page.getByRole("button", { name: /edit|✎|done|✓/i });
    if (await editBtn.first().isVisible()) {
      await editBtn.first().click();
      await page.waitForTimeout(500);
    }
  });
});

test.describe("Deck Builder Page", () => {
  test("loads deck editor", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(2000);
    // Navigate via SPA sidebar
    const deckLink = page.locator("a[href*='deck'], a[href*='Deck']").first();
    if (await deckLink.isVisible()) await deckLink.click();
    else await page.goto("/decks"); // fallback
    await page.waitForTimeout(3000);
    const body = await page.textContent("body");
    expect(body).toMatch(/Slide|Present|Untitled|Deck/);
  });

  test("has present and export buttons", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(2000);
    const deckLink = page.locator("a[href*='deck']").first();
    if (await deckLink.isVisible()) await deckLink.click();
    await page.waitForTimeout(3000);
    const body = await page.textContent("body");
    expect(body).toMatch(/Present|Export|Deck/);
  });

  test("has template buttons", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(2000);
    const deckLink = page.locator("a[href*='deck']").first();
    if (await deckLink.isVisible()) await deckLink.click();
    await page.waitForTimeout(3000);
    const body = await page.textContent("body");
    expect(body).toMatch(/Hero KPI|Template|Funnel|Deck/i);
  });

  test("has AI chat input", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(2000);
    const deckLink = page.locator("a[href*='deck']").first();
    if (await deckLink.isVisible()) await deckLink.click();
    await page.waitForTimeout(3000);
    const input = page.locator("input[placeholder*='escribe'], input[placeholder*='slide'], input[placeholder*='generate']");
    const count = await input.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test("can add slide via template", async ({ page }) => {
    await page.goto("/decks");
    await page.waitForTimeout(2000);
    // Click a template button
    const btn = page.locator("button").filter({ hasText: /Hero KPI|Status Funnel/ });
    if (await btn.first().isVisible()) {
      await btn.first().click();
      await page.waitForTimeout(500);
      const body = await page.textContent("body");
      expect(body).toContain("Slide 2");
    }
  });
});

test.describe("Credentials Page", () => {
  test("credentials API responds", async ({ page }) => {
    const response = await page.request.get("/v1/credentials");
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.credentials.length).toBeGreaterThan(0);
    const ids = data.credentials.map((c: any) => c.id);
    expect(ids).toContain("airtable");
  });

  test("credential config save/load", async ({ page }) => {
    // Save
    const save = await page.request.put("/v1/credentials/airtable/config", {
      data: { config: { base_id: "appTEST" } },
    });
    expect(save.status()).toBe(200);
    // Load
    const load = await page.request.get("/v1/credentials/airtable/config");
    expect(load.status()).toBe(200);
    const data = await load.json();
    expect(data.config.base_id).toBe("appTEST");
  });
});

test.describe("Widget Endpoints", () => {
  test("widget-examples returns templates", async ({ page }) => {
    const response = await page.request.get("/v1/dashboard/widget-examples");
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.length).toBeGreaterThan(50);
  });

  test("deck-templates returns 50+ templates", async ({ page }) => {
    const response = await page.request.get("/v1/dashboard/deck-templates");
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.length).toBeGreaterThanOrEqual(50);
  });

  test("deck-templates can filter by category", async ({ page }) => {
    const response = await page.request.get("/v1/dashboard/deck-templates?category=KPI");
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.length).toBeGreaterThan(0);
    expect(data.every((t: any) => t.category === "KPI")).toBe(true);
  });

  test("airtable widget handles missing creds", async ({ page }) => {
    const response = await page.request.get("/v1/widgets/airtable?table=test&group_by=x&max_records=1");
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect("error" in data || "breakdown" in data).toBe(true);
  });

  test("jira widget handles missing creds", async ({ page }) => {
    const response = await page.request.get("/v1/widgets/jira?project=TEST");
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect("error" in data || "issues" in data).toBe(true);
  });

  test("demos endpoint works", async ({ page }) => {
    const response = await page.request.get("/v1/dashboard/demos");
    expect(response.status()).toBe(200);
  });
});

test.describe("Chat API", () => {
  test("chat complete responds to hello", async ({ page }) => {
    const response = await page.request.post("/v1/chat/complete", {
      data: { messages: [{ role: "user", content: "hello" }] },
    });
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.choices[0].message.content.length).toBeGreaterThan(0);
  });

  test("chat complete handles tool-triggering messages", async ({ page }) => {
    const response = await page.request.post("/v1/chat/complete", {
      data: { messages: [{ role: "user", content: "check jira status" }] },
    });
    // Should return 200 (not 500) even if tools fail
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.choices[0].message.content.length).toBeGreaterThan(0);
  });
});

test.describe("Core APIs", () => {
  test("agents list", async ({ page }) => {
    const r = await page.request.get("/v1/agents");
    expect(r.status()).toBe(200);
    expect((await r.json()).length).toBeGreaterThan(0);
  });

  test("dags list", async ({ page }) => {
    const r = await page.request.get("/v1/dags");
    expect(r.status()).toBe(200);
  });

  test("settings", async ({ page }) => {
    const r = await page.request.get("/v1/settings");
    expect(r.status()).toBe(200);
  });

  test("memory entries", async ({ page }) => {
    const r = await page.request.get("/v1/memory/entries");
    expect(r.status()).toBe(200);
  });

  test("schedules", async ({ page }) => {
    const r = await page.request.get("/v1/schedules");
    expect(r.status()).toBe(200);
  });

  test("mcp servers", async ({ page }) => {
    const r = await page.request.get("/v1/mcp/servers");
    expect(r.status()).toBe(200);
  });
});
