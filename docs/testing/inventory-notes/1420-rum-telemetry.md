---
inventory-delta:
  packages/hive-conductor/backend/tests: +14
---

# 1420 — RUM collector contract tests

#1420's production perceived-load path ends in a new backend surface:
`POST /v1/rum/events` (ingest), `GET /v1/rum/events` (operator read-back) and
`GET /v1/rum/events/summary` (grouped aggregation), backed by a new bounded
in-memory store (`services/rum_store.py`). The fourteen new node IDs in
`packages/hive-conductor/backend/tests/test_rum_routes.py` pin the collector
contract itself:

- fail-closed ingest — with `RUM_INGEST_ENABLED` at its default a valid batch
  is answered 202 and **discarded** (read-back and summary stay empty), while a
  malformed envelope is still refused 422 even then (no path stores anything);
- the schema is enforced server-side as defense in depth: oversized batches,
  unknown schema versions, route templates carrying a query string, and
  request ids outside the `X-Request-ID` charset are refused before the store;
- an accepted event is projected onto the approved fields only — a test posts
  a payload carrying a URL with a token, a response body, a password and a
  prompt and asserts none of them reach the stored observations;
- correlation with the existing `RequestIDMiddleware` id: a response-carried
  id round-trips into the store verbatim, the collector's own response carries
  an id too, and a transport-failure outcome stores `request_id: null` rather
  than fabricating one;
- retention is bounded — the ring evicts oldest past the cap, the setting is
  clamped, and the batch cap is pinned equal to the frontend's
  `MAX_BATCH_EVENTS` (a file-level cross-check between `routes/rum.py` and
  `lib/rumSchema.ts` until a shared source of truth exists).

The frontend side of #1420 (reporter, redaction rules, live collection) is
tested by `tests/e2e/rum-telemetry.spec.ts`, which is Playwright, not
pytest-collected — this suite's collected count is unaffected by it. No other
suite moved: no existing tests were edited, and the only production-code
edits adjacent to tests are the new route/store/settings fields above.

## Independent verification (this worktree, 2026-10-07)

Beyond the pytest suite above, the issue's live acceptance checks were
re-executed against a fresh production build served by the real backend
(`vite build` with `VITE_RUM_ENABLED=true VITE_RUM_SAMPLE_RATE=1
VITE_RUM_BUILD_ID=verify-1420`; the built bundle carries no `debugApi` code —
the DEV gate folds it away entirely):

- controlled load + shared-client requests shipped finite non-negative
  `load`/`LCP`/`api_request` timings; receipts read back via `GET
  /v1/rum/events` (total=7) and grouped by `GET /v1/rum/events/summary`;
- every emitted `request_id` was one of the `X-Request-ID`s that page's
  responses actually carried (3/3); a planted URL query token appears in no
  payload;
- a build without `VITE_RUM_ENABLED` and a build with
  `VITE_RUM_SAMPLE_RATE=0` each sent zero requests across navigations and
  the pagehide flush;
- against a collector answering 500, flush attempts stayed flush-paced
  (>10 s apart), the reporter went permanently silent after the 3rd
  consecutive in-document failure, and the page kept rendering; a pagehide
  beacon counts as success when the browser queues it (documented
  "queuing = success" semantics) and thereby resets the streak;
- `scripts/check-suite-inventory.py` passes: this suite collects 3437 ==
  baseline + all note deltas including the +14 above.
