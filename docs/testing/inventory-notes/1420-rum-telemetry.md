---
inventory-delta:
  packages/hive-conductor/backend/tests: +30
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

## OpenAPI drift repair (+1, same file, 2026-10-08)

The byte-cap redesign of `ingest_events` (manual `request.stream()` read) made
FastAPI stop emitting the ingest contract from the route signature: the
regenerated `src/api/types.gen.ts` silently lost `RumBatchIn`,
`WebVitalEventIn`, `ApiRequestEventIn` and the operation's `requestBody`/422 —
the #1048 drift step (`dump-hive-openapi.py` -> `gen:api` ->
`git diff --exit-code`) went red only in CI. The repair documents the manual
read instead of surrendering it: the route declares `openapi_extra`
(requestBody `$ref` `RumBatchIn`, 422 `HTTPValidationError`), and
`routes/rum.py::ensure_openapi_contract` (installed by `main.py`) registers the
three component schemas by rendering them through FastAPI itself on a scratch
app where the batch IS a declared body parameter — the exact rendering a
parameter-driven route gets on this FastAPI version, so the regenerated
`types.gen.ts` is byte-identical to the committed one (zero frontend churn).
`test_openapi_document_keeps_the_ingest_contract` (+1 node) pins the document
at the source: the three schemas exist, the ingest operation declares the body
and the 422 envelope, and every `$ref` the components make resolves. Against
the pre-repair tree the test fails on the first assertion (the components were
absent — the regeneration diff that went red in CI).

Round note (2026-10-08, CI-repair): the OpenAPI repair above also completes
the shipped-surface matrix for the never-mounted rendering route
(`POST /rum-contract` on the throwaway app, classified `local-only` with its
never-routable truth contract) and re-validates the full local battery post
develop-sync: ruff check/format clean, `dump-hive-openapi` -> `gen:api` ->
`git diff --exit-code` green with the committed `types.gen.ts` byte-identical,
`tsc --noEmit` clean, backend suite 3549 passed + 19 skipped, vulture
(CI invocation) 1328/1328 banked, enumerations + provenance, shipped-surface,
suite inventory, doc links, frontend typed-client all green. The one
deliberate residual is unchanged and outside a repair change's authority:
`check-route-permissions.py` fails on `/v1/rum` until the maintainer lands the
`exempt::/v1/rum` grant at the merge base (two-merge doctrine), then this PR
declares `exempt_reason: authenticated-only` and deletes the baseline row.

## Diff-coverage repair (+2, same file, 2026-10-08)

The merge-queue's "Coverage gate (publish-set floor + diff coverage)" was red
on exactly one file: `services/rum_store.py` measured 85.7% of its 154 changed
lines against the per-file 90% floor (reproduced locally with CI's own
producers — `coverage run --source=packages/hive-conductor/backend` over the
backend suite plus the `--source=scripts` producer, then
`scripts/check-diff-coverage.py coverage.xml --base <merge base>`). The
uncovered lines were the store's defense-in-depth half: every malformed-event
rejection path in `project_web_vital` / `project_api_request` (unknown type,
unknown metric, negative/non-numeric values, empty and over-length route
templates, boolean timestamps, lower-case verbs, impossible status classes,
unknown outcomes, non-string and charset-failing request ids), the per-event
reject-and-continue inside `ingest`, and the settings-broken fallbacks in
`get_store()` / `rum_ingest_enabled()`. Two node IDs close exactly those
gaps through the public store API —
`test_store_projection_drops_every_malformed_event_without_widening_storage`
(one valid event among thirteen malformed shapes: kept == 1, every malformed
shape counted rejected, nothing but the approved projection stored) and
`test_store_and_switch_fail_closed_when_settings_cannot_be_read` (a raising
`get_settings()` yields the documented default ring bound and a disabled
switch, never an exception that would 500 a beacon). Post-change the gate is
green at the CI thresholds: "every measured file this change touches is at or
above 90% lines / 80% branch arcs", with the backend suite at 3551 passed +
19 skipped.

## Route-permissions resolution (+6, 2026-10-08, the merge-queue red)

The merge-queue's `integration-scope` aggregator was red because the Quality
gate's `check-route-permissions.py` failed on exactly one finding: `/v1/rum`
was a NEW undeclared route prefix, and the previously documented resolution
path (maintainer lands an `exempt::/v1/rum` grant at the merge base, then the
PR declares `exempt_reason: authenticated-only`) is outside a worker branch's
authority — the two-merge doctrine means a same-branch grant is invisible.

The path that IS inside one merge is the one the gate's own docstring names:
"Declaring a permission is a tightening and needs nothing more." Declaring
one truthfully required making the middleware actually enforce it, and the
place enforcement belongs was already a real gap, not an invented one: the
read-back endpoints serve an instance-wide aggregate of every principal's
navigation telemetry (route templates, session ids, timings) to ANY
authenticated session, while the middleware's own philosophy (the
persona-wide feedback check) keeps exactly that kind of cross-principal
aggregate operator-only. So this round:

- `middleware/auth.py` `_PROTECTED_OPS["GET"]` gains `/v1/rum -> rum.read`:
  the raw ring and the summary are operator reads; POST ingest stays
  authenticated-only on purpose — every session's reporter must beacon
  without task-scoped elevation or the ring starves of ordinary traffic
  (the ROUTE_EXEMPT entry for the POST is kept, its reason updated);
- `quality/route-permissions.json` declares `/v1/rum` with
  `permission: rum.read` (owner, disposition, and the reason spelling out
  both halves: GET gated, POST authenticated-only), and
  `quality/route-permissions-baseline.json` drops its tolerated row — the
  ratchet is back to zero undeclared prefixes, with no grant required;
- `docs/RUM.md`'s operator row and smoke procedure now say what is true:
  ingest accepts any authenticated session, read-back needs the admin role
  or an assigned + elevated `rum.read`;
- six node IDs pin the boundary from both files: in `test_rum_routes.py`,
  `TestReadBackScope` proves a daily session's beacons are accepted while
  its read-back is 403 naming `rum.read` (and the admin session then reads
  the same ring), plus the unauthenticated 401-not-403 degenerate path; in
  `test_auth_middleware.py`, `TestRumReadBackScope` runs the standard
  capability matrix for the new scope — no scope 403, scope without
  elevation 403, scope + task elevation passes, ingest without any scope
  passes the gate. Against the pre-change tree (enforcement entry removed)
  the three refusal assertions fail with 200s — they pin the regression
  they name.

The e2e read-back (`rum-telemetry.spec.ts`) now reads the receipts through
an admin API context and asserts the PM session's own read-back is refused
403 — the maintainer's-view comment made literal. Backend suite after this
round: 3557 passed + 19 skipped (3576 collected).

Executed evidence (this worktree, compose images rebuilt from this tree):
`check-route-permissions.py` → "ok: 41 declared, 0 tolerated undeclared
prefix(es), none new"; enumerations + provenance, vulture (CI invocation,
1328/1328 banked), shipped-surface, typed-client, doc-links, ruff
check/format, suite inventory (3576 == baseline + all note deltas) all
green; the #1048 drift sequence green with `types.gen.ts` byte-identical
(re-verified before and after this round's edits — the prior round's fix
holds); the diff-coverage gate re-run with CI's own producers over the
two measured roots this branch touches (`--source=packages/hive-conductor/backend`
over the backend suite, `--source=scripts` over the root suite) → "every
measured file this change touches is at or above 90% lines / 80% branch
arcs"; compose e2e-ui leg 158 passed in 3.0 m (both rum specs included,
the operator/403 assertions live), compose api-tests leg 10 passed +
13 skipped.

## Repair round at the merge head (2026-10-08, `476ca0b67d61`)

The independent-verify round after the route-permissions fix was BLOCKED
only on its environment: `docker compose -f docker-compose.test.yml up` could
not reach a Docker daemon, so the browser half of the acceptance checks was
left UNVERIFIED (backend/auth pytest evidence was green). This round re-ran
the same two rum specs against the same code without a container runtime,
so the evidence no longer depends on one being up:

- production SPA built with the compose harness's own build args
  (`VITE_RUM_ENABLED=true VITE_RUM_BUILD_ID=e2e-local`, `npm run build` —
  `tsc --noEmit` x2 + vite), served by the real backend started locally
  with the compose service's env (`RUM_INGEST_ENABLED=true`,
  `SESSION_COOKIE_SECURE=false`, `ALLOW_INSECURE_TRANSPORT=true`, fresh
  `CONDUCTOR_DATA_DIR`), `python -m uvicorn main:app` on a scratch port;
- `rum-telemetry.spec.ts`: **7/7 passed** — the five Node-side redaction
  rules plus the live path (finite non-negative `load`/`LCP` measurements,
  `api_request` durations, every emitted `request_id` one the server
  actually issued, the planted URL token and raw agent id absent from all
  outgoing bytes, and the operator read-back + summary grouping with the
  PM session's own read-back refused 403);
- `rum-client-off-switches.spec.ts`: **5/5 passed** (off-flag and absent-env
  builds send nothing, sampled-out sends nothing, the breaker trips and
  stays silent, the buffer ships exactly `MAX_BATCH_EVENTS`, and the
  no-`PerformanceObserver` page ships the `load` fallback). Outside the
  playwright image the spec's container defaults need the overrides it
  already provides: `E2E_SRC_ROOT=<packages/hive-conductor>` and
  `E2E_NODE_PATHS=<tests/e2e>/node_modules`;
- full backend suite re-run at this head: **3557 passed + 19 skipped**
  (3576 collected), `--suite packages/hive-conductor/backend/tests`
  inventory match re-confirmed; frontend `eslint .` 0 errors / 94 warnings
  (budget 96).

Every locally-runnable gate the merge queue named was re-verified green at
`476ca0b67d61` against the merge base `34795962548a`:
`check-route-permissions.py` ("ok: 41 declared, 0 tolerated undeclared
prefix(es), none new" — the resolution above holds, no grant needed), the
#1048 drift sequence (`dump-hive-openapi.py` -> `gen:api` ->
`git diff --exit-code -- .../types.gen.ts`, byte-identical), the CI-exact
vulture invocation (1326/1326 banked, 0 unclassified),
`check-shipped-surface-truth.py`, `check-frontend-typed-client.py`,
`check_enumerations.py`, and `ruff check` / `ruff format --check`.
