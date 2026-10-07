---
inventory-delta:
  packages/hive-conductor/backend/tests: +21
  packages/hive-conductor/tests/e2e: +0
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

## Review-repair round (+7 more, same file, 2026-10-07)

Seven further node IDs pin the contracts tightened by the PR review:

- envelope identifiers are retained: every stored observation carries the
  batch's `build_id` / `session_id` (re-validated in the store as defense in
  depth — a batch whose identifiers fail the charset is rejected wholesale),
  and the summary groups per build so the build-over-build comparison the
  ring exists for is actually readable (`test_summary_groups_are_split_per_build`,
  `test_store_rejects_wholesale_when_envelope_identifiers_fail_the_charset`);
- the raw body is capped (64 KiB) before JSON parsing, while enabled or not —
  `extra="ignore"` cannot bound bytes, so padding an unknown top-level field
  is refused 413 before any parsing in either collector state
  (`test_oversized_body_is_refused_before_parsing_even_while_disabled`,
  `test_oversized_body_is_refused_while_enabled_too`);
- `ts` must be finite and non-negative on both event types — Python's JSON
  parser accepts NaN/Infinity literals and a retained non-finite value would
  break the read-back's own serialization
  (`test_non_finite_and_negative_timestamps_are_refused`);
- summary percentiles are nearest-rank (`ceil(p·n) - 1`): for 20 samples p95
  is the 19th ordered value, not the maximum, and an even-sized p50 is the
  lower middle (`test_percentiles_are_nearest_rank`; the even-group p50
  assertion in `test_summary_groups_by_metric_route_and_outcome` was
  corrected to the same definition);
- first-store construction is single-flight — two concurrent first requests
  cannot each build a store while the first caller is still inside
  `get_settings()` (`test_concurrent_first_requests_construct_exactly_one_store`).

Two shipped-behavior notes for reviewers of this delta: the disabled
collector still refuses a schema-invalid batch 422 (the pinned fail-closed
test above is unchanged — only a *valid* batch gets the 202-and-discard),
and on the frontend the document load metrics now carry the route captured
at init rather than the mutable location at flush time.

The frontend side of #1420 (reporter, redaction rules, live collection) is
tested by `tests/e2e/rum-telemetry.spec.ts`, which is Playwright, not
pytest-collected — this suite's collected count is unaffected by it. No other
suite moved: no existing tests were edited, and the only production-code
edits adjacent to tests are the new route/store/settings fields above.

## Client-side off-switches (repair round, 2026-10-07)

Acceptance check 4's client half had no test: nothing ran a build with
collection off, a sampled-out session, a rejecting collector or a page
without `PerformanceObserver`. `tests/e2e/rum-client-off-switches.spec.ts`
now pins each against the shipped `lib/rum.ts` itself, bundled per scenario
into an ephemeral page (the reporter is a per-page-load singleton whose env
is baked at build time, so a fresh bundle is the only fresh instance):

- a build with `VITE_RUM_ENABLED=false` — and a plain-esbuild bundle where
  `import.meta.env` is absent entirely, the defensive `?? {}` path — never
  constructs a reporter: reported events buffer nothing, the pagehide flush
  sends nothing;
- `VITE_RUM_SAMPLE_RATE=0` (the deterministic sampled-out rate) behaves
  identically;
- three consecutive rejected sends trip the breaker: each failed batch is
  spliced before the send so nothing is retried (POST count moves only when
  the page pushes again), the reporter goes permanently silent after the
  third rejection — further events and a pagehide boundary produce no
  request — and the page renders on throughout;
- the buffer is bounded: 30 reported events ship exactly one batch of
  `MAX_BATCH_EVENTS` (conservation pinned against the pending count), and
  the raw agent id and query string feeding those events appear nowhere in
  the wire bytes;
- a page with `PerformanceObserver` stubbed out still initializes, ships the
  documented `load` fallback (finite, non-negative) and never emits LCP or a
  page error.

The spec imports `lib/rumSchema.ts` from Node and bundles `lib/rum.ts` at
scenario build time, so `tests/Dockerfile.playwright` now COPYs both files —
previously `rum-telemetry.spec.ts`'s Node-side import of `rumSchema` failed
collection in the built image ("Cannot find module
../../frontend/src/lib/rumSchema"), which is what the
`hive-conductor-e2e-ui` red at ff943dc was. Both suites are Playwright, so
the e2e suite's pytest-collected count is unchanged: the `+0` delta above is
explicit, not an omission.

Executed evidence (this worktree, image rebuilt from the fixed head): the
compose-built `e2e-tests` image runs `npx playwright test --list` clean —
153 tests in 31 files, rum-client-off-switches' five scenarios collected —
the five scenarios pass in that image with `--retries=0` (5 passed, 6.8 s),
and the full `hive-conductor-e2e-ui` compose run (live hive service built
with `VITE_RUM_ENABLED=true` + `RUM_INGEST_ENABLED=true`, all 31 spec files)
finishes **153 passed** in 3.0 m — the same command ci.yml's job runs, with
rum-telemetry.spec.ts's live path included, no source mounts. Harness note
for reviewers: the reporter reads env through one `(import.meta).env ?? {}`
variable, so the scenarios bake the whole `import.meta.env` object via
esbuild `define` — per-key defines never reach the module (the first draft's
did, every scenario silently ran disabled, and the two send-nothing tests
passed for the wrong reason; the object-define form is what makes the
enabled scenarios actually collect).

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

## Re-validation after the repair round (this worktree, 2026-10-07)

- `uv run ruff check .` and `uv run ruff format --check .`: clean.
- `pytest packages/hive-conductor/backend/tests -q`: 3461 collected,
  3456 passed + 5 skipped, 0 failed (includes the 21 in
  `test_rum_routes.py`).
- `scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`:
  collected 3461 == baseline + all note deltas including the +21 above.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (the CI invocation): 1328 reviewed
  identities, 0 unclassified — clean.
- Frontend: `tsc -p tsconfig.json --noEmit` clean, `eslint .` 0 errors /
  94 warnings (budget 96, all pre-existing), `npm run build` succeeds.

## Ledger and surface-classification gates touched by the repair

- `scripts/check_enumerations.py`: `POST /v1/rum/events` is classified in
  `ROUTE_EXEMPT` (the same documented decision every other authenticated-only
  mutating surface carries, e.g. `/v1/pm-fleet/distill`) —
  `check-enumerations-provenance.py` passes with no candidate-approved
  expansion.
- `quality/frontend-typed-client-baseline.json`: the three `raw_fetch` rows
  for App.tsx's startup probes are deleted — the probes now go through
  `instrumentedGet` in `src/lib/` (where the shared HTTP helpers live), so
  the ratchet shrinks by 3 rather than moving the rows. Gate passes with
  "none new".
- `quality/shipped-surface-truth.json`: the ingest route is classified
  (`domain-state`, effect owner `services/rum_store.py`) — the shipped-surface
  matrix is complete again.
- `quality/route-permissions-baseline.json`: records the real current state
  (`/v1/rum` undeclared). **Residual, deliberate:** the gate still fails on
  exactly one finding — a NEW prefix (or its `exempt_reason` declaration)
  needs a `route-permissions` grant already landed at the merge base
  (`quality/ratchet-authorizations.json` as of `b1f17b8d6`), which is the
  repository's two-merge doctrine and outside a repair change's authority.
  No grant exists for `/v1/rum` at the base; declaring a `permission` instead
  would be a false enforcement claim (the middleware elevates nothing for
  `/v1/rum`). Landing order for the maintainer: (1) the grant, (2) this
  PR's registry declaration (`exempt_reason: authenticated-only`) + deletion
  of the baseline row. Every other locally-runnable gate is green.
