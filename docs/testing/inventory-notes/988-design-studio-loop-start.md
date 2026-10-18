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
