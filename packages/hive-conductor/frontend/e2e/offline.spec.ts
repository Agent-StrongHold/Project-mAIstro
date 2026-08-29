import { test, expect } from "./fixtures";

/**
 * The Conductor runs on a mini-PC that may have no internet at all, and until
 * #377 the first thing every page did was fetch three typefaces from Google
 * Fonts. On an air-gapped box that is a blocked request in the critical path;
 * on a connected one it is every visitor's IP handed to a third party.
 *
 * Asserting "we removed the <link>" would prove nothing durable — the next
 * import, icon set or analytics snippet puts the dependency straight back. So
 * this cuts the network at the browser instead and asks the page to render
 * anyway: any request that leaves this origin is aborted, exactly as it would
 * be behind an air gap, and the run records what tried.
 */
test.describe("Air-gapped rendering", () => {
  async function airgap(page: import("@playwright/test").Page, origin: string) {
    const escaped: string[] = [];
    await page.route("**/*", async (route) => {
      const url = route.request().url();
      if (url.startsWith(origin) || url.startsWith("data:") || url.startsWith("blob:")) {
        await route.continue();
        return;
      }
      escaped.push(url);
      await route.abort();
    });
    return escaped;
  }

  test("nothing the app loads leaves its own origin", async ({ page, baseURL }) => {
    const escaped = await airgap(page, new URL(baseURL!).origin);

    await page.goto("/chat");
    await expect(page.locator(".icon-sidebar").first()).toBeVisible({ timeout: 10000 });

    expect(escaped).toEqual([]);
  });

  test("the self-hosted typefaces resolve with the network cut", async ({ page, baseURL }) => {
    // A missing font is the quiet failure: the stack falls through to the
    // system face, the page still renders, and every other assertion here
    // still passes. `document.fonts.check` is the difference between "it
    // looked fine" and "the family the design asks for is actually there".
    const escaped = await airgap(page, new URL(baseURL!).origin);
    await page.goto("/chat");

    const resolved = await page.evaluate(async () => {
      const families = ["Inter Variable", "JetBrains Mono Variable"];
      await Promise.all(families.map((family) => document.fonts.load(`400 16px '${family}'`)));
      return families.filter((family) => document.fonts.check(`400 16px '${family}'`));
    });

    expect(resolved).toEqual(["Inter Variable", "JetBrains Mono Variable"]);
    expect(escaped).toEqual([]);
  });
});
