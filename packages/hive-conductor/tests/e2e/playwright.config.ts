import { defineConfig } from "@playwright/test";

const baseURL = process.env.HIVE_BASE_URL || "http://localhost:8101";
const isCI = !!process.env.CI;

// CI budget, and why it is not the local one.
//
// This suite has to finish inside ci.yml's `hive-conductor-e2e-ui` step
// timeout, and the step also pays for a `docker compose --build` first. At the
// local settings (60s x 12 specs x 2 attempts = up to 24 minutes of test time
// alone) it never finished, so the step was killed mid-run — and Playwright's
// list reporter emits per-test failure detail at the END of the run. The result
// was a job that reported 12 red ticks and not one line saying why: no error,
// no timeout message, no call log. Diagnosing it was impossible by
// construction.
//
// Under CI the budget is cut so the run completes and reports:
//   20s x 12 specs x 2 attempts  ~= 8 minutes worst case.
//
// 20s is still generous for a containerised app on the same compose network —
// the passing `hive-conductor-e2e` API suite against the same service finishes
// in under a second. Retries are 1 everywhere: while the suite was being
// stabilised they were 0 in CI so a deterministic failure paid no retry tax,
// with the stated plan to turn them back on "once it is green and flake is
// the real risk". That is now the observed state — the suite runs 219 specs
// at workers:1, and the failures it throws are environmental, not product
// regressions: CI run 39856259683 lost one spec to a chromium "Target
// crashed" renderer death (218/219 passed) and a local run at the same
// commit lost a different spec to a stalled SPA shell render (213 passed).
// A retry re-runs only the failed spec in a fresh context, so an
// environmental crash recovers while a deterministic failure still fails on
// attempt 2; `trace: "on-first-retry"` below keeps the diagnostics for any
// failure that survives the retry.
const TEST_TIMEOUT_MS = isCI ? 20_000 : 60_000;

export default defineConfig({
  testDir: ".",
  timeout: TEST_TIMEOUT_MS,
  retries: 1,
  workers: 1,
  // Surface the failure reason as each test finishes rather than only in the
  // end-of-run summary, so a killed run still leaves evidence behind.
  reporter: isCI ? [["line"]] : [["list"]],
  use: {
    baseURL,
    headless: true,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
  ],
});
