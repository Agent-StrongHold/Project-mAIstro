---
inventory-delta:
  tests/: +4
---
# fix-m1-1144-javascript-discovery

The shipped-surface detector now covers the JavaScript/TypeScript forms that
escaped the initial inventory:

- Express-style `app`, `router`, `api`, `server`, and suffixed router/app/server
  mutating registrations are recorded as `mutating-api-route` surfaces.
- A route path in a non-literal expression receives a stable line/digest
  identity rather than being silently omitted.
- A mutating `fetch` whose endpoint is a literal string binding is resolved to
  the same route identity as an inline fetch. This covers Canvas `llmClient.js`.

The Canvas Express handlers, Canvas client LLM calls, and direct Azure image
request are classified in `quality/shipped-surface-truth.json`. The matrix
still fails closed when a newly discovered route or fetch lacks a disposition.
The Python multi-statement fake-success coverage from the preceding #1144
slice remains in `tests/test_shipped_surface_truth.py`.
