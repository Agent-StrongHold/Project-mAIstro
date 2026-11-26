import { defineConfig } from "@playwright/test";

// Self-contained runner for the gateway model-discovery specs (#287). These
// specs mock every /v1/settings/models response, so a bare Vite dev server is
// enough — no backend stack required. `npx playwright test
// --config=playwright.model-discovery.config.ts` owns the server lifecycle.

const PORT = 8107;
// devskim: ignore DS162092 -- test-only loopback URL for the ephemeral Vite
// server this config owns; PLAYWRIGHT_BASE_URL overrides it for CI/remote
// runners, matching playwright.config.ts.
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
    // devskim: ignore DS162092 -- the runner deliberately hosts its own
    // throwaway dev server on loopback; --host 127.0.0.1 keeps it
    // unreachable from outside the machine under test.
    command: `npm run dev -- --port ${PORT} --strictPort --host 127.0.0.1`,
    // devskim: ignore DS162092 -- readiness poll of the same loopback server.
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 90_000,
  },
});
