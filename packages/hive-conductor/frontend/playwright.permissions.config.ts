import { defineConfig } from "@playwright/test";

// Route-intercepted UI contract tests: Playwright owns the Vite lifecycle;
// no deployed backend or privileged fixture account is needed.
const PORT = 8108;
// devskim: ignore DS162092 -- ephemeral test-only loopback server.
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["workspace-permissions.spec.ts", "workspace-attention-elevation.spec.ts"],
  timeout: 30000,
  retries: 0,
  workers: 1,
  use: { baseURL: BASE_URL, headless: true },
  webServer: {
    // devskim: ignore DS162092 -- ephemeral test-only loopback server.
    // DevSkim: ignore DS162092 -- test-only loopback server command.
    command: `npm run dev -- --port ${PORT} --strictPort --host 127.0.0.1`,
    url: BASE_URL, // DevSkim: ignore DS162092 -- test-only loopback URL.
    reuseExistingServer: false,
    timeout: 90_000,
  },
});
