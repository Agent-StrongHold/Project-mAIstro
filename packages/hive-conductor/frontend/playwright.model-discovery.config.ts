import { defineConfig } from "@playwright/test";

// Self-contained runner for the gateway model-discovery specs (#287). These
// specs mock every /v1/settings/models response, so a bare Vite dev server is
// enough — no backend stack required. `npx playwright test
// --config=playwright.model-discovery.config.ts` owns the server lifecycle.

const PORT = 8107;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "setup-model-discovery.spec.ts",
  timeout: 30000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: `http://localhost:${PORT}`,
    headless: true,
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    timeout: 90_000,
  },
});
