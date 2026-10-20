# #1572 repair round 75 — first-hand re-verification at 8628dc56e (dispatch head)

Round 75 re-derived the block and re-executed the full acceptance battery first-hand at
dispatch head `8628dc56e078adad1fed67cbb8c9e023bb1b208e` (worktree clean; the only delta
since round 74 is round-74's docs note, so the tree is code-identical to every battery
since round 63). Nothing was assumed from prior rounds' claims. Driver checks this round
are green at this exact head: `uv sync --locked --extra dev` ok, `ruff check .` ok,
`ruff format --check .` ok (3288 files), focused 9-file suite 161 passed / 28 skipped,
suite inventory ok (16334 = 16334, 0 duplicates).

## Blocker re-derived first-hand (unchanged, external)

- B1. `git fetch origin` re-run: origin/develop tip == merge-base ==
  `3c761d14db944a727fa0744444bc67cfe36d49f7` (**UNCHANGED**, `git rev-list --count
  HEAD..origin/develop` = 0 — no develop sync conflict, nothing to merge);
  `git grep GoalStatus origin/develop -- quality/` → no matches (0 grants on develop).
- B2. `uv run python scripts/check-execution-lifecycles.py` — the exact CI argv
  (`.github/workflows/quality.yml:1541`, no args) — **exit 1**, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted
  base and has no already-landed authorization` (19 -> 20 lifecycles).
- B3. Merge-queue `test: failure` re-derived 1:1: `uv run pytest
  tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**; the failed
  test `test_the_shipped_ledger_matches_the_shipped_code` (line 368-374, `gate.main()`)
  prints the gate's stdout verbatim (same sole finding). The coverage `combine` step
  failure is inherited from this dead root-suite producer, not an independent deficit.
- B4. Two-merge rule re-read in source this round: `scripts/ratchet_provenance.py`
  `load_authorizations` (:478+) reads grants **from the base revision**, docstring
  verbatim: "a new grant does not take effect in the change that introduces it …
  Authorizing a floor-raise is now two merges". The candidate ledger already classifies
  GoalStatus DOMAIN (`quality/execution-lifecycles.json:89`) and the gate still fails —
  self-classification is non-authorizing. The branch's
  `quality/ratchet-authorizations.json` is **byte-identical to origin/develop**
  (`cmp` against `git show origin/develop:...` passes; `git diff origin/develop HEAD --
  quality/ratchet-authorizations.json` empty), so an in-branch grant re-add is a proven
  no-op. Round 74's executed plumbing simulation (SIM = develop+grant parented candidate,
  `RATCHET_BASE_REV=SIM` → gate **exit 0**, "authorized: maistro.goals.model::GoalStatus
  #1572 … OK: 20 vocabularies all classified") remains the demonstration that once the
  grant lands on develop the branch passes with zero branch edits; the base-not-in-
  ancestry control run failed, confirming merge-base reduction.
- B5. Lane-brief vulture CI-repair exception re-checked at the exact CI argv
  (`.github/workflows/quality.yml:1079`, `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`): **exit 0**,
  1323 reviewed identities = 1323 findings, nothing unbanked. The amendment-permitted
  ledger (`quality/vulture-baseline.json`) has **no target** this round.
- B6. No legitimate in-branch resolution exists: renaming/removing the issue-mandated
  `active/satisfied/cancelled/failed/superseded` vocabulary violates issue scope or
  dodges the detector (prohibited weakening); `RATCHET_BASE_REV=HEAD` is
  self-reference, refused by design; dropping the candidate ledger row fails the same
  gate from the other side.

## Acceptance battery re-executed first-hand this round (fresh DBs)

- A1. Fresh pg18 (`pgvector/pgvector:pg18`, container r75g18, port 55475):
  `DATABASE_URL=… uv run alembic upgrade head` from empty → **single head 063**, final
  step `062 -> 063, The canonical Goal store`, and the chain preserves develop's merged
  identities verbatim (`043_invocation_quota_door -> 056` user-model #1047, `056 -> 057`
  planner stability #863, then 058…062). `alembic heads` = `063 (head)`; `alembic
  current` = `063 (head)`; psql shows exactly `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions`; `alembic_version` = 063.
  → AC8 (identity/ancestry preserved, Goal appends after the integrated develop head
  under an unused centrally coordinated id).
- A2. Goals suite, pg18, PG legs **required**:
  `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=… uv run
  pytest packages/maistro-core/tests/goals -q` → **70 passed / 0 failed / 0 skipped**.
  Covers: 3-backend conformance round-trip (AC1), append-only revisions + stale-refusal
  + concurrent CAS single-winner (AC2), subgoal lineage preserving parent Goal/Project +
  explicit recorded agent transition (AC3), immutable Run binding (AC4), two-principals
  two-Workspace isolation with foreign == missing (AC5), shipped-Container wiring
  (AC6), schema agreement, restart readback.
- A3. Both supported PostgreSQL majors: same battery on fresh pg17 (`pgvector/pgvector:
  pg17`, container r75g17, port 55476): empty → single head 063, goals suite
  **70 passed / 0 failed / 0 skipped** with legs required.
- A4. Migration chain + single-head + installed-base upgrade:
  `MAISTRO_TEST_DATABASE_URL=… uv run pytest tests/migrations/test_migration_chain.py
  tests/migrations/test_single_migration_head.py tests/migrations/
  test_goal_installed_base_upgrade.py -q` → **29 passed, 0 skipped**. The installed-base
  file is exactly the issue's closure test: it upgrades databases migrated by the
  *actual* develop snapshots `c560d4c` (user-model 056) and `4675101` (planner 057)
  forward to the candidate head with **no stamp edit and no reset** (AC9/AC10).
- A5. Downgrade/refusal leg executed directly on pg17: `alembic downgrade -1` →
  `063 -> 062`, `canonical_goal*` tables 3 → **0**; `alembic upgrade head` → back to
  **3** tables, stamp `063` (AC11).
- A6. AC7 convergence freeze at the CI argv (`.github/workflows/formal-conformance.yml:77`):
  `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94` →
  **exit 0**: "M1 convergence freeze: no unapproved new architecture island".
- A7. Production composition re-read in source: `container.py:44` imports
  `wire_goal_store`, `:273` `goal_store` field, `:276-286` the `goal_reader`
  ScopedGoalStore seam, `:2414` `create_container` awaits `wire_goal_store(db_pool,
  pg_pool=pg_pool)`; maistro-server composes it (`main.py:29` import, `:344`
  `create_container(...)`); Hive composes it (`backend/adapters/maistro_core.py:148`
  import, `:195` `create_container(config)`). Both shipped compositions reach the
  wiring; `test_goal_wiring.py` (inside the 70) proves the shipped Container exposes it.
- A8. `uv run mypy` over the seven package srcs → **Success: no issues found in 899
  source files**.

## Verdict

**BLOCKED** on the external maintainer execution-lifecycles grant for
`maistro.goals.model::GoalStatus` (PR #1938 is exactly that grant; #1136/#1833 are the
landed two-merge precedents). Every issue acceptance criterion is proven by executed
evidence at this head; the sole red CI gate (`check-execution-lifecycles` + its
shipped-ledger test + inherited coverage combine) is unresolvable in-branch by the
repo's own deliberate two-merge design: the grant must land on develop first, then this
branch passes the gate and the test with **zero branch edits** (demonstrated by
execution in round 74 B6). No code, test, or ledger changes were made this round; no
inventory delta. Local-only note: `quality/ac-state.json` is untracked gitignored
operator scratch from gate runs; `tests/test_branch_independence_repository.py::
test_every_quality_json_state_surface_is_classified_once` fails on it in this worktree
only (CI passes it); left untouched.
