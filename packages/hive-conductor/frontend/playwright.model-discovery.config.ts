import { defineConfig } from "@playwright/test";

// Self-contained runner for the gateway model-discovery specs (#287). These
// specs mock every /v1/settings/models response, so a bare Vite dev server is
// enough — no backend stack required. `npx playwright test
// --config=playwright.model-discovery.config.ts` owns the server lifecycle.

const PORT = 8107;
// Test-only loopback URL for the ephemeral Vite server below; PLAYWRIGHT_BASE_URL
// overrides it for CI/remote runners, matching playwright.config.ts.
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "setup-model-discovery.spec.ts",
  timeout: 30000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: BASE_URL,
    headless: true,
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort --host 127.0.0.1`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 90_000,
  },
});
