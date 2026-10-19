# Issue #1572 repair verification — round 79 (2026-10-12)

Dispatch head `7f2de2b4b95b337bdd556e6f942d2e7ca9b383b9`, base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Tree clean at start; this round is docs-only (no code/test/ledger edits, no inventory delta).

## Verdict

**BLOCKED** — unchanged, on the external maintainer execution-lifecycles grant for
`maistro.goals.model::GoalStatus`. Every acceptance criterion of the issue itself is proven
below; the sole red leg is a quality-gate authorization that structurally cannot be satisfied
inside this branch (two-merge rule). Once the grant lands on develop (grant-only PR #1938
shape, #1136/#1833 precedent), this branch passes the gate and its test with zero branch edits
(execution-proven in rounds 74/77: simulation base = develop + grant → gate exit 0).

## Blocker re-derived first-hand this round (none assumed)

- Gate at the exact CI argv (`.github/workflows/quality.yml:1541`,
  `uv run python scripts/check-execution-lifecycles.py`, no extra args): **exit 1**, sole
  finding `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19 → 20).
- Shipped-ledger test `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`:
  **1 failed / 28 passed**, captured stdout byte-identical to the gate run = the merge-queue
  `test: failure` 1:1 (the coverage `combine` step failure is inherited from this producer).
- Two-merge mechanics re-read from source, not assumed: `scripts/ratchet_provenance.py:478-495`
  `load_authorizations` reads grants **from the base revision** (docstring: "a new grant does
  not take effect in the change that introduces it … two merges"); the gate reads the base at
  `check-execution-lifecycles.py:773-783` and `_unauthorized_additions` (`:704-707`) keeps a
  candidate classification from authorizing a newly added identity.
- Candidate ledger already classifies the vocabulary: `quality/execution-lifecycles.json:89-92`
  `GoalStatus` → `DOMAIN` with full rationale. Classification is present, so classification is
  not the defect; the grant in the base is the missing input.
- `origin/develop` re-fetched this round: tip == merge-base `3c761d14db94` (branch 180 ahead);
  `git grep GoalStatus origin/develop -- quality/` = 0; `git diff origin/develop --
  quality/ratchet-authorizations.json` = empty (in-branch grant content identical to develop =
  proven no-op). No develop sync conflict exists.
- No legitimate in-branch repair: renaming/removing `GoalStatus` violates the issue-mandated
  lifecycle (active/satisfied/cancelled/failed/superseded) or dodges the detector = gate
  weakening; `RATCHET_BASE_REV=HEAD` is refused by `_refuse_self_reference`
  (`ratchet_provenance.py:258`).

## Lane-brief vulture CI-repair exception — no target

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` (exact argv, quality.yml:1076-1081): **exit 0**, 1323 reviewed = 1323
findings, unclassified 0, never_allowlist 0. The permitted ledger amendment has nothing to
amend; the failing gate is execution-lifecycles, not vulture.

## Acceptance criteria re-executed first-hand this round

Fresh pg18 (pgvector/pgvector:pg18, 18.x) database `r79g18` created this round; all DSNs
pointed at it.

- **Types/protocol + lifecycle + stores (AC1-AC3, AC5):**
  `MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest packages/maistro-core/tests/goals -q` →
  **70 passed / 0 failed / 0 skipped**: 3-backend (memory/SQLite/PG) conformance round-trip,
  append-only revisions with stale-refusal and CAS exactly-one-winner, terminal states final,
  subgoal lineage preserving parent/Project with explicit recorded agent transition,
  two-principals isolation with foreign == missing, restart readback, Container wiring test.
- **Run binding (AC4):** immutable `goal_id`/`goal_revision` provenance covered in the same 70
  on the migrated DB (`test_run_goal_binding.py` requires a migrated DB; the empty-DB
  `UndefinedTableError` is the documented operator artifact, avoided this round).
- **Migrations:** `uv run alembic upgrade head` on the empty DB → single head `063`, chain
  ends `062 -> 063, The canonical Goal store`, through the merged `056` (user-model) and `057`
  (planner) identities with no reassignment; `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions` all present at stamp `063`. Full battery
  `uv run pytest tests/migrations -q` → **168 passed / 0 skipped / 0 failed** including the
  installed-base forward upgrades from the actual pre-Goal develop snapshots `c560d4c` (056)
  and `4675101` (057) without stamp edits, plus downgrade/refusal/reapplication.
- **AC7 (no second executor):** `grep -rn "GoalRun\|OrchestratorRun" packages/*/src
  --include='*.py'` → exit 1 (absent); `uv run python scripts/check-m1-convergence-freeze.py
  --base 3c761d14db944a727fa0744444bc67cfe36d49f7` (CI argv, formal-conformance.yml:70-77) →
  **exit 0**, "no unapproved new architecture island".
- **AC6 (production composition):** source-read this round —
  `packages/maistro-core/src/maistro/container.py:44` (import `wire_goal_store`), `:273`
  (`goal_store` field), `:276-286` (`goal_reader` = `ScopedGoalStore` authorized seam),
  `:2414` (`wire_goal_store` inside `create_container`), `:2701` (passed into the container);
  `packages/maistro-server/src/maistro_server/main.py:29` (`create_container`); Hive adapter
  `packages/hive-conductor/backend/adapters/maistro_core.py:148,195` (note: `backend/`, not
  `src/` — earlier round notes' path shorthand resolved to the real file this round).
- **Typecheck:** `uv run mypy` over the seven package source trees → **Success: no issues
  found in 899 source files**.

## Driver logs (this job, head `7f2de2b4b`)

sync ok / `ruff check .` "All checks passed!" / `ruff format --check .` 3288 files /
focused pytest 161 passed 28 skipped / suite inventory ok (16334 identities).

## Environment notes

- `quality/ac-state.json` is an untracked, gitignored (`.gitignore:81`) local scratch file;
  it is the only cause of a local-only `test_branch_independence` failure here and is left
  untouched (CI passed it).
- Operator-env lesson recorded for future rounds: the goals PG legs need **both**
  `MAISTRO_TEST_PG_DSN` (conformance, run binding) **and** `MAISTRO_TEST_DATABASE_URL`
  (schema agreement); with only the former set, 6 schema-agreement tests error on an empty
  `MAISTRO_TEST_DATABASE_URL` under `MAISTRO_REQUIRE_PG_LEGS=1`. Both were set for the 70-pass
  run above.
