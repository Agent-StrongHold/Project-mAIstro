---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/hive-conductor/tests/e2e: +0
---
# Design Studio loop start mints canonical objects (#988, M7-A12)

Opening work in Design Studio now mints canonical objects — a Project-scoped
Goal revision, a CreativeBrief revision on that exact revision, a pack binding,
and one canonical Run carrying the exploration params — and never a
product-local `DesignRun`. The visual-mode picker stays available below the
loop start as the execute-backend choice, not a competing start.

Two test additions, one per failure shape:

- `packages/hive-conductor/backend/tests/test_design_loop_start_contract.py`
  (+3 pytest nodes, collected by the ledger): a static source contract over the
  frontend tree that fails if (a) a `DesignRun` identifier is declared in
  non-comment code, (b) loop-named state (`goal`/`brief`/`pack`/`loop`/`run`)
  moves into a `localStorage`/`sessionStorage` key as a client-persist system
  of record, or (c) a pack id (`book`/`game`/`product`/`atelier`) becomes a
  route segment (both JSX `<Route path="/book">` and an object-literal
  `[{ path: "/book" }]` route table are read) or an `Atelier*.tsx` page
  appears. Comments are stripped
  before the scan so documenting the prohibition never trips it; substring
  matching (not `\b`) is deliberate so snake_case storage keys cannot slip
  through a word-boundary hole.
- `packages/hive-conductor/tests/e2e/design-studio-loop-start.spec.ts`
  (browser-only, `+0` like the other `*.spec.ts` journeys): three Playwright
  journeys against the real page — mint order (Goal → CreativeBrief → Run,
  asserted from recorded request order, with pack/width/policy asserted on the
  Run payload and absent from the Goal payload), refresh-restore of the ids
  from the APIs (the stubs return the minted records only over GET, so a
  client-store restore cannot pass), and the honest disabled state when a
  canonical surface 404s (control stays disabled after 2.5s, cause names the
  missing surface, and no mint request is fired).

The `+0` e2e delta follows the `design-studio-keyboard-769.md` convention:
browser-only specs are not pytest-collected and stay out of the ledger.

## Executed evidence

Negative controls (synthetic tree outside the repo, real scanner module):
`DesignRun` type declaration, a `hive_design_loop` localStorage key, an
object-literal `/book` route, and an `Atelier.tsx` page are each caught by
their contract test; the real tree passes all three.

Against the worktree's own build served by an isolated backend
(pgvector/pg18 container on 127.0.0.1:18844, alembic-migrated, uvicorn on
127.0.0.1:18990, frontend rebuilt from this tree):

- `uv run pytest packages/hive-conductor/backend/tests/test_design_loop_start_contract.py -q`
  → `3 passed`.
- `HIVE_BASE_URL=http://127.0.0.1:18990 npx playwright test design-studio-loop-start.spec.ts`
  → `3 passed`.
- Regression: `npx playwright test design-studio-truthfulness.spec.ts design-studio-keyboard.spec.ts`
  → `9 passed`.
- `tsc -p tsconfig.json --noEmit` (via `npm run build`) → clean.
- `npx eslint src/pages/DesignStudio.tsx --max-warnings 0` → clean.
- `scripts/check-frontend-api-routes.py` → ok (the loop probes `/v1/goals`,
  `/v1/creative-briefs`, `/v1/design/packs`, `/v1/runs`, none of which are
  mounted at this base; each call carries the waiver naming its issue, so the
  loop start stays honestly disabled here per #286 until those surfaces ship).
- `scripts/check-shipped-surface-truth.py` → complete; `scripts/check-suite-inventory.py`
  → ok; `ruff check`/`format --check` on the new test file → clean.

## Re-validation round (independent reproduction)

The whole battery was re-run from scratch on a fresh harness in the same
worktree (pgvector/pg18 container on 127.0.0.1:18844, alembic-upgraded, backend
`uvicorn main:app` on 127.0.0.1:18990 serving this tree's rebuilt
`frontend/dist`, no route stubs unless a test installs its own):

- Contract test `3 passed`; ruff check + format clean; `tsc --noEmit` clean;
  `eslint DesignStudio.tsx --max-warnings 0` clean.
- `scripts/check-frontend-api-routes.py` → ok (166 call sites / 215 routes);
  `check-shipped-surface-truth.py` complete; `check-suite-inventory.py` ok
  (14 suites).
- `design-studio-loop-start.spec.ts` → `3 passed`; regression
  `design-studio-truthfulness.spec.ts` + `design-studio-keyboard.spec.ts` →
  `9 passed`.
- Negative controls re-proven in a synthetic tree outside the repo with the
  real scanner module: clean frontend copy passes; each of a `DesignRun` type
  declaration, a `hive_design_loop` localStorage key, an object-literal
  `[{ path: "/book" }]` route in App.tsx, and an `Atelier.tsx` page is caught.
- Real-backend honest-disabled journey (ad-hoc spec, no request interception
  at all): logged in against the live server, all four canonical surfaces
  report `unavailable` with `HTTP 404 from /v1/goals`, `/v1/creative-briefs`,
  `/v1/design/packs`, `/v1/runs` — verified server-side too (authenticated
  curl → 404 on all four; OpenAPI lists none of them among its 203 paths), the
  start control stays disabled past a 2.5 s wait, and zero mint POSTs fire.
  This closes the gap where the shipped spec's missing-surface journey stubs
  the 404s: the stub shape and the server's real answer are now both proven.

Repair note (this round): the E2E recorder originally counted any request
whose URL contained `/v1/design/projects` or `/v1/chat` as a "model call";
the page's legitimate mount-time `GET /v1/design/projects` listing
(`DesignStudio.tsx`) tripped it against a real backend. The recorder now
counts invocations (POST) only, which is what the #987 invariant means. The
status line also rendered `cause ?? message`, which permanently shadowed the
restore/mint outcome message once the loop was open; it now shows both.

## Verification round (independent, CI-shaped harness)

Re-proven from scratch in the same worktree with a harness matching the CI
`hive-conductor-e2e-ui` shape rather than the earlier pg-backed one: frontend
rebuilt (`npm run build` → tsc both configs + vite, clean), backend run
DB-less (in-memory stores, the `docker-compose.test.yml` hive env: no
`DATABASE_URL`) via the worktree venv on 127.0.0.1:18990, serving that dist.

- Contract test `3 passed`; ruff check + format clean on it;
  `tsc --noEmit` clean; `eslint DesignStudio.tsx --max-warnings 0` clean.
- `design-studio-loop-start.spec.ts` → `3 passed`;
  `design-studio-truthfulness.spec.ts` + `design-studio-keyboard.spec.ts` →
  `9 passed`; backend suite still collects 2946 nodes (ledger sums: baseline +
  this note's +3).
- Negative controls re-proven in a fresh synthetic tree outside the repo with
  the real scanner module: clean copy passes; `DesignRun` type declaration, a
  `hive_design_loop` `localStorage.setItem`, an object-literal
  `[{ path: "/book" }]` beside a JSX `/game` route in App.tsx, and an
  `Atelier.tsx` page are each caught. Scope note taken from the module's own
  docstring: comment-stripping guards the `DesignRun` identifier scan only —
  the storage-key scan reads raw text, so it can false-positive on a comment
  quoting a forbidden call (fail-noisy direction only; the real tree passes).
- Live server, no stubs anywhere: authenticated `POST /v1/auth/login` then
  `GET` on all four canonical surfaces → `404` on every one; `/openapi.json`
  lists none of `/v1/goals`, `/v1/creative-briefs`, `/v1/design/packs`,
  `/v1/runs`. An ad-hoc no-interception journey (removed after the run) then
  showed the real page against that real server: all four surfaces report
  `unavailable` with `HTTP 404 from /v1/goals` visible, the start control
  stays disabled past a 2.5 s wait, and zero mint POSTs fire.

## Verification round (independent re-run on the CI compose image)

Re-proven on this tree's `hive-conductor-e2e-ui` artifact path: the `hive`
compose service built from this worktree (repo-root context, so the served SPA
is this tree's frontend, compiled by the same Dockerfile CI uses), published to
a host port away from a pre-existing local 8101 listener of unknown provenance:

- `uv run pytest packages/hive-conductor/backend/tests/test_design_loop_start_contract.py -q`
  → `3 passed`; repo-wide `uv run ruff check .` clean; format clean on the
  test file; `tsc -p tsconfig.json --noEmit` and `tsconfig.node.json` clean.
- `scripts/check-frontend-api-routes.py` → ok (177 call sites / 257 routes);
  `check-shipped-surface-truth.py` complete; `check-suite-inventory.py` ok
  (21 suites); `git diff --numstat origin/develop -- quality/` empty (no
  ledger drift).
- Against that container-served build, `HIVE_BASE_URL` pointed at the
  published port: `design-studio-loop-start.spec.ts` → `3 passed`; regression
  `design-studio-truthfulness.spec.ts` + `design-studio-keyboard.spec.ts` →
  `11 passed`.
- Negative controls re-proven in a fresh synthetic tree outside the repo with
  the real scanner module: the clean copy passes, then each injected shape is
  caught by name — a `DesignRun` type declaration in `pages/DesignRun.tsx`, a
  `hive_design_loop` `localStorage.setItem`, an object-literal
  `[{ path: '/book' }]` in `App.tsx`, and a `pages/Atelier.tsx` page.
- Harness truth at this base (OpenAPI, 250 paths): `/v1/design/packs` IS
  mounted (#793 shipped) — the other three are not. An ad-hoc no-interception
  journey against that real server reproduced the honest mixed state exactly:
  1 `ready` (packs) + 3 `unavailable` rows each carrying `HTTP 404 from
  /v1/goals` / `/v1/creative-briefs` / `/v1/runs`, the start control disabled
  immediately and still disabled after a 2.5 s wait, the state line saying
  "Nothing is simulated", zero mint POSTs, and in-session `GET`s returning
  `404` on all three missing surfaces. This is the issue's own fallback
  behavior proven live, not a stub artifact.

## CI-gate repair round (fitness scan + typed-client ratchet)

The merge-queue evaluation at `c7cbc04` failed two leaf gates; both failures
were scan-geometry collisions with the implementation, not behavior gaps, and
this round repairs the implementation's shape without changing behavior or
test counts (`inventory-delta` above is unchanged):

- **Architecture fitness** (`test_no_competing_execution_lifecycle_name[DesignRun]`):
  the maistro-core fitness scan is raw-text over `frontend/src` — it does not
  strip comments, unlike this branch's own backend contract test. Two comments
  in `DesignStudio.tsx` that said "There is no DesignRun" therefore tripped the
  `\bDesignRun\b` tripwire. The token is now absent from the entire frontend
  tree (the contract test's comment-stripped scan still passes; nothing it
  guards was weakened).
- **Frontend typed-client ratchet**: the nine loop client-projection types
  declared in `pages/DesignStudio.tsx` counted as new hand-typed debt in
  `pages/` (96 → 105), unauthorized at the trusted merge base, and their
  insertion also shifted `PersistedFixedPageArtifact` off its ledgered line-85
  identity. The projections moved to the shared module
  `src/lib/designLoop.ts` (outside the pages/components scan roots, the home
  of shared frontend shapes), the page imports them, and every ledgered
  hand-typed identity in the page is back on its exact baseline line
  (96 → 96, "none new"); `quality/frontend-typed-client-baseline.json` is
  untouched.

Executed evidence (this worktree, head b9b1d7232f):

- `scripts/check-frontend-typed-client.py` → ok (26 raw fetch / 96 hand-typed,
  none new); `scripts/check-frontend-api-routes.py` → ok (177 call sites /
  257 routes); `git diff --numstat origin/develop -- quality/` empty.
- `uv run pytest packages/maistro-core/tests/fitness/test_no_second_design_product.py -q`
  → `13 passed`; the backend contract test → `3 passed`.
- The CI `coverage (no services)` selection run verbatim
  (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests --timeout=30 -q`)
  → `17795 passed, 1302 skipped, 7 xfailed, 0 failed` (6:45). The
  "RuntimeError: Event loop is closed" lines in that CI job's log are
  `PytestUnhandledThreadExceptionWarning`s from aiosqlite worker threads —
  present in this local run too as warnings, never as failures; the job's
  failing assertion was the fitness scan above.
- Frontend `npm run build` (tsc both configs + vite) clean; `npm run lint`
  → 0 errors (47 warnings ≤ 96 cap).
- Compose-shape E2E on the `hive-conductor-hive` image rebuilt from this
  tree: `design-studio-loop-start.spec.ts` + `design-studio-truthfulness.spec.ts`
  + `design-studio-keyboard.spec.ts` → `14 passed (11.5s)`, including the
  mint-order (Goal → CreativeBrief → Run with pack/width/policy on the Run
  payload only), the refresh-restore-from-APIs journey, and the
  missing-surface honest-disabled journey.
- `scripts/check-suite-inventory.py` → ok (21 suites, counts unchanged);
  `uv run ruff check .` and `uv run ruff format --check .` clean.
