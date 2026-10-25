import { test, expect, type Page } from "@playwright/test";

/**
 * The backend API reference renders under the enforced CSP (#1425).
 *
 * `/docs` is the one page the security policy used to blank out: FastAPI's
 * default handler loaded the Swagger UI stylesheet and bundle from jsdelivr,
 * the favicon from fastapi.tiangolo.com, and inlined its bootstrap script —
 * every one refused by `script-src 'self'` / `style-src 'self'`. The page now
 * ships vendored first-party assets (`backend/static/swagger-ui/`), and these
 * tests prove the outcome the acceptance check names: the reference renders
 * with zero CSP violations, not merely a 200 with an empty Swagger container.
 *
 * Header and HTML checks live in `backend/tests/test_docs_first_party.py`;
 * they cannot prove that Swagger executed, which is why this file exists. The
 * first test also cuts the network at the browser (the `offline-assets` trick)
 * so the page must render with only shipped, same-origin resources — the
 * bundled-approach clause of the acceptance criteria.
 */

interface Captures {
  escaped: string[];
  cspViolations: string[];
  pageErrors: string[];
  failedRequests: string[];
}

/** The handle `swagger-initializer.js` installs on `window`. */
interface SwaggerUiHandle {
  /** The Redux state as an Immutable map; the fetched spec lives under it. */
  getState?: () => { getIn?: (keys: string[]) => unknown };
}

function capture(page: Page, origin: string): Captures {
  const captures: Captures = {
    escaped: [],
    cspViolations: [],
    pageErrors: [],
    failedRequests: [],
  };

  // The air gap: every request that would leave this origin is aborted,
  // exactly as it would be on the air-gapped mini-PC this product runs on.
  void page.route("**/*", async (route) => {
    const url = route.request().url();
    if (url.startsWith(origin) || url.startsWith("data:") || url.startsWith("blob:")) {
      await route.continue();
      return;
    }
    captures.escaped.push(url);
    await route.abort();
  });

  // CSP refusals surface as console errors naming the policy; a page that
  // renders but bleeds violations fails here.
  page.on("console", (msg) => {
    if (
      (msg.type() === "error" || msg.type() === "warning") &&
      /content.security.policy/i.test(msg.text())
    ) {
      captures.cspViolations.push(msg.text());
    }
  });
  page.on("pageerror", (error) => captures.pageErrors.push(String(error)));
  page.on("requestfailed", (request) =>
    captures.failedRequests.push(
      `${request.url()} ${request.failure()?.errorText ?? "failed"}`,
    ),
  );

  return captures;
}

test.describe("API reference under the enforced CSP", () => {
  test("renders the real operation list from first-party assets only", async ({
    page,
    baseURL,
  }) => {
    const captures = capture(page, new URL(baseURL!).origin);

    const schemaResponse = page.waitForResponse((r) => r.url().endsWith("/openapi.json"));
    const response = await page.goto("/docs", { waitUntil: "domcontentloaded" });
    expect(response?.status()).toBe(200);

    // The API title renders — from the fetched schema, not from markup alone.
    await expect(page.locator(".info .title")).toHaveText(/Hive Conductor/, {
      timeout: 15_000,
    });

    // The actual operation list renders, and an operation expands: the bundle
    // executed and mounted, which is the part header checks can never prove.
    const opblock = page.locator(".opblock");
    await expect(opblock.first()).toBeVisible({ timeout: 15_000 });
    expect(await opblock.count()).toBeGreaterThan(0);
    await opblock.first().click();
    await expect(page.locator(".opblock-body").first()).toBeVisible();

    // The real OpenAPI document was fetched successfully and is what the UI
    // parsed — `window.ui` is the handle the vendored initializer installs.
    expect((await schemaResponse).status()).toBe(200);
    const specTitle = await page.evaluate(() => {
      const ui: SwaggerUiHandle | undefined =
        (window as unknown as { ui?: SwaggerUiHandle }).ui;
      return (ui?.getState?.().getIn?.(["spec", "json", "info", "title"]) as string) ?? null;
    });
    expect(specTitle).toBe("Hive Conductor");

    // Zero of anything: no blocked third-party attempt, no CSP refusal, no
    // uncaught error, no failed request — the audit's console is quiet
    // because the page renders, not because nobody looked.
    expect(captures.escaped).toEqual([]);
    expect(captures.cspViolations).toEqual([]);
    expect(captures.pageErrors).toEqual([]);
    expect(captures.failedRequests).toEqual([]);
  });

  test("the docs page ships the enforcing policy itself", async ({ request }) => {
    const response = await request.get("/docs");
    expect(response.status()).toBe(200);

    const csp = response.headers()["content-security-policy"];
    expect(csp).toBeTruthy();
    expect(csp).toContain("script-src 'self'");
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).not.toContain("unsafe-eval");
    // Enforced, not a rollout-only copy nobody's browser obeys.
    expect(response.headers()["content-security-policy-report-only"]).toBeUndefined();
  });
});
