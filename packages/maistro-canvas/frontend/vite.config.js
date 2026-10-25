import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    // Without this the suite runs under the default `node` environment and
    // every DOM-touching test in tests/renderingPipeline.test.js fails with
    // "document is not defined". jsdom was already a declared devDependency —
    // it was simply never wired up, which is why those 10 failures went
    // unnoticed: no workflow ran this suite at all.
    environment: 'jsdom',
  },
  server: {
    port: 5173,
    // Loopback by default. This dev server proxies /litellm straight to the
    // operator's LiteLLM on :4000, so binding 0.0.0.0 published an
    // unauthenticated proxy to those credentials on every interface. Set
    // CANVAS_DEV_HOST=0.0.0.0 deliberately if you need LAN access.
    host: process.env.CANVAS_DEV_HOST || '127.0.0.1',
    proxy: {
      '/litellm': {
        target: 'http://localhost:4000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/litellm/, ''),
      },
      '/api': {
        target: 'http://localhost:5174',
        changeOrigin: true,
      },
    },
  },
})
