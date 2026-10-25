import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_BASE_PATH lets the gateway serve Hive at a sub-path (e.g. /pm/) without
// 404ing on assets. Defaults to "/" so dev + standalone builds are unaffected.
// Declared inline to keep the Hive tsconfig free of an @types/node dependency
// (vite.config.ts runs in Node, but the rest of the frontend is browser-targeted).
declare const process: { env: Record<string, string | undefined> };
const basePath = process.env.VITE_BASE_PATH || "/";

export default defineConfig({
  base: basePath,
  plugins: [react()],
  server: {
    proxy: {
      "/v1": {
        target: "http://localhost:8101",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8101",
        changeOrigin: true,
      },
    },
  },
});
