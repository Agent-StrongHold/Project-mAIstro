/**
 * The shared API client gives up on a hung or failed request instead of
 * leaving a spinner up forever, and never shows the raw transport failure
 * (#1423).
 *
 * `lib/api.ts`'s `request()` wrapped `fetch` with no timeout or
 * `AbortController` -- only Chat's own streaming fetch and the dashboard
 * assistant widget guarded against a hung request; the ~28 other pages that
 * go through the shared client did not. It now aborts after 30s, and any
 * transport-level failure (the abort, a dropped connection, offline, CORS)
 * is wrapped in the same human `ApiError` #1436 gave HTTP-status failures,
 * rather than surfacing as a raw `TypeError: Failed to fetch`.
 *
 * The 30s production timeout itself is deliberately not exercised here:
 * this suite's own CI budget is 20s per spec (see playwright.config.ts),
 * so waiting out the real timer isn't practical at this layer. Instead this
 * drives the same try/catch/ApiError-wrapping code the timeout path shares
 * by making the request fail at the transport level immediately
 * (`route.abort()`) -- fast, deterministic, and exercising exactly the
 * branch that needs to turn "fetch threw" into human, retryable copy
 * instead of a raw error name.
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test("a request that fails at the transport level shows a human, retryable message", async ({
  page,
}) => {
  await setupIfNeeded(page);
  await loginAsAdmin(page);
  await page.addInitScript(() => window.localStorage.setItem("hive_onboarded", "1"));

  await page.route("**/v1/work-items*", (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.abort("connectionfailed");
  });

  await page.goto("/work-items", { waitUntil: "domcontentloaded" });
  const toast = page.getByRole("status").filter({ hasText: /./ });
  await expect(toast).toBeVisible({ timeout: 15000 });
  const text = (await toast.textContent()) ?? "";

  expect(text).not.toContain("TypeError");
  expect(text).not.toContain("Failed to fetch");
  expect(text.toLowerCase()).toContain("check your connection");

  await page.unroute("**/v1/work-items*");
});
