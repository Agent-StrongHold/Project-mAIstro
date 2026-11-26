/**
 * Infinite pulse/spin/bounce animations respect `prefers-reduced-motion`
 * (#1415).
 *
 * Only one `prefers-reduced-motion` block existed (the skeleton pulse added
 * for #1408), and it covered three selectors. Three infinite animations sat
 * outside it: the dashboard status dot's `status-pulse` (2.2s), the chat
 * typing indicator's `bounce` (1.4s), and a running tool step's
 * `loading-spin` (1s) -- all of them looped forever regardless of the OS
 * motion setting. All three now sit in the same guarded block as the
 * skeleton pulse. This test exercises the one of the three that's always on
 * screen without further setup: the Dashboard header's "Operational"
 * status pill. The other two (`.typing-indicator .dot`,
 * `.tool-step--running .tool-step-icon`) share the identical CSS rule in
 * the same media block -- confirmed by reading the stylesheet -- but aren't
 * independently driven here since reaching them needs a live chat/tool
 * turn.
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin, setupIfNeeded } from "./session";

test("the dashboard status dot only pulses when the OS has no reduced-motion preference", async ({
  page,
}) => {
  await setupIfNeeded(page);
  await loginAsAdmin(page);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  const dot = page.locator(".dashboard-status-dot");
  await expect(dot).toBeVisible({ timeout: 15000 });
  await expect(dot).toHaveCSS("animation-name", "none");

  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const dotAgain = page.locator(".dashboard-status-dot");
  await expect(dotAgain).toBeVisible({ timeout: 15000 });
  await expect(dotAgain).toHaveCSS("animation-name", "status-pulse");
});
