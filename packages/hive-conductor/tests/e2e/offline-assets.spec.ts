import { test, expect, type Page } from "@playwright/test";

/**
 * Air-gapped rendering (#377).
 *
 * The Conductor runs on a mini-PC that may have no internet at all, and until
 * #377 the first thing every page did was fetch three typefaces from Google
 * Fonts. On an air-gapped box that is a blocked request in the critical path;
 * on a connected one it is every visitor's IP handed to a third party.
 *
 * Asserting "we removed the <link>" would prove nothing durable — the next
 * import, icon set or analytics snippet puts the dependency straight back. So
 * this cuts the network at the browser and asks the app to load anyway: every
 * request that would leave this origin is aborted, exactly as it would be
 * behind an air gap, and the run records what tried.
 *
 * Deliberately unauthenticated. The first document a browser is given is the
 * one an air gap breaks first, it carries the same bundle and stylesheet as
 * every other route, and a test that had to log in first would be proving the
 * login flow as well as this.
 *
 * `escaped` is the second line, not the first: the Content-Security-Policy now
 * names no external origin, so a reintroduced font host is refused before the
 * request is made and never reaches this route handler. Both are worth having.
 * The policy is what protects users; this is what notices when the app starts
 * needing something the policy forbids, which is how the two stay in step.
 */

async function airgap(page: Page, origin: string) {
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

test.describe("Air-gapped rendering", () => {
  test("the app loads with every off-origin request aborted", async ({ page, baseURL }) => {
    const escaped = await airgap(page, new URL(baseURL!).origin);

    // `domcontentloaded`: some routes hold a long-lived connection open, so the
    // load event says nothing useful about the page being usable.
    await page.goto("/", { waitUntil: "domcontentloaded" });

    // Something interactive, not just markup: a page whose stylesheet or
    // bundle had been blocked would still return a <body>.
    await expect(page.locator("input, button").first()).toBeVisible({ timeout: 15000 });
    expect(escaped).toEqual([]);
  });

  test("the self-hosted typefaces resolve with the network cut", async ({ page, baseURL }) => {
    // A missing font is the quiet failure: the stack falls through to the
    // system face, the page still renders, and every other assertion here
    // still passes.
    //
    // The face is read out of `document.fonts` and its status checked, NOT
    // asked for with `document.fonts.check()`. That returns true for a family
    // nothing defines — measured here against a build with no @font-face at
    // all, where it happily reported an invented family as available, because
    // a CSS font shorthand always resolves to *something*. An assertion that
    // cannot fail is worse than none.
    const escaped = await airgap(page, new URL(baseURL!).origin);
    await page.goto("/", { waitUntil: "domcontentloaded" });

    const loaded = await page.evaluate(async () => {
      const families = ["Inter Variable", "JetBrains Mono Variable"];
      await Promise.all(families.map((family) => document.fonts.load(`400 16px '${family}'`)));
      const faces = Array.from(document.fonts).map((face) => ({
        family: face.family.replace(/^['"]|['"]$/g, ""),
        status: face.status,
      }));
      return families.filter((family) =>
        faces.some((face) => face.family === family && face.status === "loaded"),
      );
    });

    expect(loaded).toEqual(["Inter Variable", "JetBrains Mono Variable"]);
    expect(escaped).toEqual([]);
  });
});
