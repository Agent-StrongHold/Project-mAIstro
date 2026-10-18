---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# #1572 independent verification round 24 (2026-10-11)

Verifier+writer pass at lane head `7f46024ce3694c6020395b480048432c7735f10f`
(the exact assigned head — the tree differs from round 23's verified content
`e01837152` by zero non-docs files), develop base `435dc1937e0407ab4de198ffcced49860bb14ad2`
(re-checked this round: `origin/develop` still `435dc193`, so there is no sync
conflict and the external-grant situation is unchanged). Every named step of the
three failed merge-queue jobs was re-executed first-hand at CI's exact
invocation; no code, tests, or ledger files were edited. The gitignored
`quality/ac-state.json` worktree artifact (`.gitignore:81`) was set aside once
for the ac-state classification test and restored sha256-identical
(`4517eb57d428db7416752f04a00c57630cc766f463fd3a5f3b8d14caadec5ecf` before and
after). The two venv-only steps CI performs outside `uv sync`
(`uv pip install -e packages/maistro-evolve`, quality.yml:811; `uv pip install
radon xenon vulture pyright interrogate pytest-timeout`, quality.yml:837) were
replicated to reach env parity; both write no tracked file.

## The named gates, re-run first-hand at this head

- **Driver's 5 deterministic checks re-run at final state:** `ruff check .` OK;
  `ruff format --check .` 3288 files; targeted goals+migrations pytest
  **161 passed, 28 skipped**; suite inventory **16334 = recorded, 0 duplicates**.
- **Pillar 1/1b coverage gates:** structural cascade, re-read in
  `.github/workflows/quality.yml` (`combine` step: `set -euo pipefail`; a
  non-zero producer aborts with "producer ... contributed no coverage data"
  before `coverage combine`/`coverage report`). The producer that aborts is the
  root-suite run whose sole in-CI red is the shipped-ledger self-check below —
  the coverage red is downstream of it, not a coverage regression.
- **Pillar 2:** `PYTHONPATH=packages/maistro-core/src uv run pytest formal/
  --timeout=120 -q` → **666 passed, 1 skipped** (after installing
  maistro-evolve exactly as CI does).
- **Pillar 3:** radon ratchet OK; single-sourced version
  (`bump_version.py --check`), release-consistency, doc-links, enumerations,
  workspace-retirement, route-permissions, principal-identity,
  frontend-typed-client, vendor_ifeval/vendor_bfcl `--check` — all exit 0.
- **Pillar 4:** `mypy --strict packages/maistro-core/src` → no issues in **789
  files**; seven-package mypy → no issues in **899 files**; pyright
  `check-pyright-report.py --baseline 21` → **16 ≤ 21**, exit 0.
- **Pillar 7:** `check-model-egress.py` exit 0 (53 direct-effect sites, all
  dispositioned); `check-foreign-harness-egress.py` exit 0;
  `check-m1-convergence-freeze.py --base 435dc1937e04...` exit 0 — no GoalRun /
  second executor / product-private Goal lifecycle; fitness suite **23 passed**;
  plus reachability, credential-authority, wiring-reads, agent-store-writes,
  contract-markers, convergence-matrix, reachability-dispositions,
  security-inventory, image-inventory, image-pins, workflow-inventory,
  backlog-consistency — all exit 0.
- **Pillar 8:** all 12 interrogate floors OK (nodes 38, durable_runs 45,
  projects 63, maistro 46, rsi 64, server 59, design 51, evolve 38 excl.
  third_party, registry 50, bootstrap 45, canvas 36, turing 24).
- **Vulture at CI's exact args** (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): **1323 = 1323, exit 0, unclassified 0** — no unbanked
  identity exists, so no `quality/vulture-baseline.json` amendment applies or
  is permitted in this round.

## Acceptance re-executed first-hand on fresh round-24 databases

- `goals_r24_pg18` (PostgreSQL 18) and `goals_r24_pg17` (PostgreSQL 17) created
  empty this round in the lane containers, each migrated through the real chain
  with `uv run alembic upgrade head`; final step `062 -> 063, The canonical
  Goal store: canonical_goals and its append-only children`; `alembic current`
  = `063 (head)` on both majors.
- Goals suite at CI env shape (`MAISTRO_REQUIRE_PG_LEGS=1`, plain
  `postgresql://` DSNs): **70/70 passed, 0 skipped on pg18 and 70/70 on pg17**.
  Leg map read from `--collect-only`: 9 model (incl. transition legality and
  the four terminal states), 33 conformance across memory/sqlite/postgres —
  round-trip, append-only chain with one CAS winner, lifecycle CAS with
  terminal-is-final, Subgoal lineage preserving parent+Project, recorded Agent
  reassignment, two principals cannot reach each other's Goals, foreign ==
  missing on reads, missing == not-found everywhere — 6 migration-063 schema
  agreement, 1 restart readback (`...survive_a_restart`), 10 wiring, 11 Run
  binding (admission binds id+revision, half-binding refused, immutable after
  admission, a Run outcome never moves Goal state). Without the env the PG legs
  skip loudly (48 passed, 22 skipped) — the fail-loud guards hold both ways.
- Installed-base + chain: `tests/migrations/test_goal_installed_base_upgrade.py`
  + `tests/migrations/test_migration_chain.py` → **26/26 on pg18 and 26/26 on
  pg17** (8 installed-base legs from the real develop snapshots c560d4c/4675101,
  both commits verified reachable in this clone; 18 chain legs: single head 063,
  downgrade round-trip, refusal+reapplication).
- Production wiring read at this head: `container.py:44` import, `:273` field,
  `:286` authorized `ScopedGoalStore` seam, `:2414`
  `goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)` inside
  `create_container`, `:2701` passed into the Container; Hive composes via
  `create_container` (`packages/hive-conductor/backend/adapters/maistro_core.py:195`);
  maistro-server `main.py:29` imports `create_container` from
  `maistro.container`.

## The three merge-queue reds — one external cause, re-proven a fourth time

1. **Quality gate:** `uv run python scripts/check-execution-lifecycles.py`
   (CI's bare invocation) exit 1 with the sole finding `maistro.goals.model::
   GoalStatus: NEW work-state vocabulary is absent from the trusted base and
   has no already-landed authorization` (19 classified -> 20 discovered).
   Root cause read in source this round: authorizations load from the merge
   base (`scripts/ratchet_provenance.py:478`, `load_authorizations(...,
   base=trusted_ref.base_sha)`; its docstring states the two-merge consequence
   is deliberate), the module `maistro/goals/model.py` does not exist at
   `435dc193` so it cannot be `visible_at_base`, and no reuse path exists —
   every base-ledger vocabulary is execution-state (Run/Attempt/Invocation/
   Node/Graph phases), while GoalStatus is desired-state and the convergence
   spine requires the two to stay distinct. No legitimate in-branch edit can
   turn this gate green: a branch-side `ratchet-authorizations.json` row is
   inert (read from base) and self-authorization is the exact path the gate
   exists to close. The unblock is a grant landing on develop first.
2. **test job:** both candidate reds re-run individually.
   `test_the_shipped_ledger_matches_the_shipped_code`
   (tests/test_check_execution_lifecycles.py) fails with the identical sole
   GoalStatus delta (1 failed, 28 passed) — same external cause as red 1.
   `test_every_quality_json_state_surface_is_classified_once`
   (tests/test_branch_independence_repository.py) fails only on the gitignored
   `quality/ac-state.json` worktree artifact and **passes** with it set aside
   (restored sha256-identical); CI checkouts cannot contain that file, so CI
   sees exactly one red here.
3. **Coverage gate:** structural cascade of red 1 via the `combine` step's
   `set -euo pipefail` (producer abort before any coverage measurement), as
   recorded under Pillar 1 above.

## Unblock remains upstream

`origin/develop` still `435dc193`; no merge conflict exists. The GoalStatus
execution-lifecycles authorization must land on develop (two-merge rule), after
which this branch's existing +4-line DOMAIN row in
`quality/execution-lifecycles.json:89` passes the gate from the new base. No
in-branch action remains: acceptance is re-proven on fresh round-24 databases
on both supported PostgreSQL majors, vulture is green at CI args (no amendment),
and every other named step of the three failed jobs exits 0.
