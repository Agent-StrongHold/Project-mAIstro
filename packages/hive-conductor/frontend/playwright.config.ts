import { defineConfig } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:8101";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: BASE_URL,
    headless: true,
    screenshot: "only-on-failure",
    // For live deployment testing, set cookies via storageState or extraHTTPHeaders
    ...(process.env.ACCESS_TOKEN ? {
      extraHTTPHeaders: {
        "Cookie": `access_token=${process.env.ACCESS_TOKEN}; sid=${process.env.SID || ""}`,
      },
    } : {}),
  },
});
