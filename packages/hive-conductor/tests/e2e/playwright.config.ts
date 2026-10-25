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
//   20s x 12 specs x 1 attempt  ~= 4 minutes worst case.
//
// 20s is still generous for a containerised app on the same compose network —
// the passing `hive-conductor-e2e` API suite against the same service finishes
// in under a second. Retries are off because a retry doubles the cost of a
// deterministic failure to buy flake tolerance this suite cannot currently use;
// turn them back on once it is green and flake is the real risk.
const TEST_TIMEOUT_MS = isCI ? 20_000 : 60_000;

export default defineConfig({
  testDir: ".",
  timeout: TEST_TIMEOUT_MS,
  retries: isCI ? 0 : 1,
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
