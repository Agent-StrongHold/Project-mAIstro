# CLAUDE.md — maistro-canvas

This file provides guidance to Claude Code (claude.ai/code) when working in `packages/maistro-canvas/`.

## What this package is

- **`src/maistro_canvas/` IS the package** — the base **canvas agent ability**: a reusable canvas engine
  (`canvas/tool.py`, `executor.py`, `compositor.py` PIL/RGBA layer assembly, `store.py`, `routes.py`) plus
  protocols (`CanvasStore`, `ImageGenClient`, `CompositorService`) and standalone API-key `auth.py`.
- **`frontend/` is a SEPARATE external application** (the book maker). It is a consumer of the canvas ability,
  not the core of the package. Architecturally it *imports* the canvas library; today the POC's Node/Express
  `server.js` mostly bypasses it (it only shells out to Python for PDF export). When adding shared canvas
  capability, put it in `src/maistro_canvas/` so any app — not just this frontend — can import it.

## Test loop (Python library)

```bash
PYTHONPATH=packages/maistro-core/src:packages/maistro-canvas/src pytest packages/maistro-canvas/tests/ -q
```
All sync; no conftest/asyncio setup. `ImageGenClient` is a protocol — tests mock it.

## Frontend (book-maker app)

```bash
cd packages/maistro-canvas/frontend
npm install
npm run dev      # Vite + Express server.js concurrently
npm run server   # Express only (port 5174)
npm run build    # Vite build
npm run test     # vitest
```

## Gotchas

- **org_id is optional here** (`protocols.py` defaults `org_id=""`) — canvas is single-tenant, unlike maistro-core.
- **Pillow ≥11** required (compositor RGBA assembly).
- **PostgreSQL store** (`canvas/store.py`) is async; tests assume mocked/in-memory stores.
- **Production needs a P40 image-gen server** alongside the app for real image generation.
- The frontend `server.js` reads its Postgres connection from **`CANVAS_DB_*` env vars** (`HOST`, `PORT`, `USER`, `PASSWORD`, `NAME`), defaulting to a local-dev setup — set these before running.
