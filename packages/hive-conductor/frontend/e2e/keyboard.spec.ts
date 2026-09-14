import { expect, test } from "./fixtures";

test.describe("Keyboard reachability", () => {
  test("skip link moves focus to the main landmark", async ({ page }) => {
    await page.goto("/chat");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("main#main-content")).toBeFocused();
  });

  test("chat model menu is operable without a pointer", async ({ page }) => {
    await page.goto("/chat");
    const modelButton = page.getByRole("button", { name: /Current model/ });
    await modelButton.focus();
    await page.keyboard.press("Enter");
    const options = page.getByRole("listbox").getByRole("button");
    await expect(options.first()).toBeVisible();
    await options.first().focus();
    await page.keyboard.press("Enter");
    await expect(modelButton).toBeFocused();
  });

  test("schedule tabs and toggles expose native keyboard controls", async ({ page }) => {
    await page.goto("/schedules");
    const historyTab = page.getByRole("tab", { name: "history" });
    await historyTab.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("execution history will appear here")).toBeVisible();
  });

  test("primary page controls remain keyboard reachable", async ({ page }) => {
    const journeys = [
      { path: "/agents", control: /View details|Create/ },
      { path: "/mcp", control: /Test connection|add server|tools/ },
      { path: "/credentials", control: /Show|save/ },
      { path: "/rsi", control: /Refresh|Start run/ },
      { path: "/cli/canvas", control: /Poster|Generate visual/ },
    ];
    for (const journey of journeys) {
      await page.goto(journey.path);
      const control = page.getByRole("button", { name: journey.control }).first();
      await expect(control).toBeVisible({ timeout: 10000 });
      await control.focus();
      await expect(control).toBeFocused();
    }
  });

  test("setup hardware choices and step navigation are buttons", async ({ page }) => {
    await page.goto("/setup");
    await page.getByLabel("Conductor name").focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    await page.getByRole("button", { name: "next" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Pick your hardware tier")).toBeVisible();
    const hardwareChoices = page.getByRole("button").filter({ hasText: /Beast|Laptop|Desktop|Server/ });
    if (await hardwareChoices.count()) {
      await hardwareChoices.first().focus();
      await page.keyboard.press("Space");
      await expect(hardwareChoices.first()).toHaveAttribute("aria-pressed", "true");
    }
  });
});
