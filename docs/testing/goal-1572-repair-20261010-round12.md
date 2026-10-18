# #1572 repair round 12 — independent re-verification at f6777acd7; prior run's BLOCKED was a provider timeout, not a check failure

Head: `f6777acd71c671d7a7ba871d0053e4893b5cdda9`, base: `4aa68edc0b6b85ae23f97e611d693927218863dc`. Worktree clean before and after; this round touched no source, test, workflow, ledger or grant file. Delta over round 11 (`8501b051f..f6777acd7`) is one docs commit, so every round-11 claim was re-proven first-hand at this head rather than trusted.

## Previous block resolved

The prior job (`aa00a7ad5f304575bcb7cc2ad4fc22b8`) ended `failure_kind: provider_error` ("Request timed out") after its own five driver checks had already passed (returncode 0 on all). The "worker requested attention: BLOCKED" was that provider death, not any red gate. No work was left uncommitted: the tree was clean at `f6777acd7`.

## Driver checks (this job, check-0..check-4.log)

All five green: `uv sync --locked --extra dev`; `ruff check .`; `ruff format --check .` (3281 files); focused Goal/parity pytest **161 passed, 28 skipped** (PG legs skip without a DSN — supplied first-hand below); `check-suite-inventory.py --suite packages/maistro-core/tests` (**16269** unique nodes, 0 duplicates).

## Fresh-install migration, executed on both supported majors

New databases (`r12_fresh`) created in `auto-1572-pg` (pg18, :55712) and `auto-1572-pg17` (pg17, :55717); `DATABASE_URL=… uv run alembic upgrade head` on each → linear chain `…057 -> 058 -> … -> 062 -> 063`, exit 0 on both; `alembic_version` = **063**; single head `('063',)` via `ScriptDirectory.get_heads()`; `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions` all present in `pg_tables`.

## PostgreSQL Goal legs — MAISTRO_REQUIRE_PG_LEGS=1, executed first-hand

- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN/MAISTRO_TEST_DATABASE_URL=…:55712/r12_fresh uv run pytest packages/maistro-core/tests/goals -q` → **70 passed** (pg18); same against :55717 → **70 passed** (pg17). Includes the shared conformance suite (memory+sqlite+postgres params) with `test_goal_revision_chain_is_append_only_with_one_cas_winner`, `test_concurrent_transitions_have_exactly_one_winner`, `test_subgoal_lineage_preserves_parent_goal_and_project`, `test_agent_reassignment_is_an_explicit_recorded_transition`, `test_a_foreign_goal_answers_exactly_like_a_missing_one` — all executed on all three backends — plus `test_goal_pg_schema_agreement.py` and `test_goal_wiring.py`.

## Installed-base upgrades — 26/26 on both majors

`MAISTRO_TEST_DATABASE_URL=…r12_fresh uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -q` → **26 passed** (pg18, 84.9s) and **26 passed** (pg17, 76.5s): live forward upgrades from the actual develop snapshots (`c560d4c` user-model 056, `4675101` planner 057) with no stamp reset, merged-identity byte-equality, single-head/unique-ids, and the durable-composition Goal/revision/bound-Run-provenance read-back on the upgraded schema.

## CI `test` job legs re-run at this head (env `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`)

- Root tree `tests/ --ignore=tests/tools/registry`: **4977 passed, 1 failed, 135 skipped** (274.9s). Sole failure = `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code` — the external GoalStatus authorization (below), unchanged.
- `packages/maistro-server/tests packages/maistro-turing/tests packages/maistro-turing/backend/tests packages/maistro-design/tests packages/maistro-ext-harness/tests packages/maistro-ext-sdk/tests`: **1837 passed, 9 skipped**.
- `packages/hive-conductor/backend/tests`: **3625 passed, 20 skipped** (156.4s).
- Full `check-suite-inventory.py`: **ok, 17 suite(s) match the recorded inventory**, 0 duplicate groups; `check-test-duplicates.py`: ok.

## Coverage producer core leg (quality.yml `coverage (no services)` equivalent)

`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests --timeout=30 -q` → **15209 passed, 1057 skipped, 3 xfailed, 0 failed** (235.6s).

## Quality-gate steps re-run at this head

`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact args) → **1323 = 1323**, no unclassified findings, no amendment. `check-m1-convergence-freeze.py --base 4aa68edc0` → green. `grep -rn 'GoalRun\|OrchestratorRun' packages/*/src --include='*.py'` → **no matches**. `tests/test_check_execution_lifecycles.py` standalone: **28 passed, 1 failed** (the same sole authorization). `check-execution-lifecycles.py` reports `19 classified -> 20 discovered` with exactly one delta: `maistro.goals.model::GoalStatus` — the branch ledger already carries the DOMAIN classification with rationale (`quality/execution-lifecycles.json`), which per the two-merge rule cannot self-authorize; the grant must land on develop in a separate change.

## Production composition (source-verified at this head)

`container.py:2365` `goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)` inside `create_container`, passed to the Container at `:2651`; principal-carrying seam `container.goals` → `ScopedGoalStore` at `:271-284`. Both shipped compositions construct it: Hive `backend/adapters/maistro_core.py:195` and maistro-server `main.py:344` both call `await create_container(...)`; `test_goal_wiring.py` (in the 70/70) proves the shipped Container exposes it.

## Criterion → first-hand evidence map

| Criterion | Evidence this round |
| --- | --- |
| Round-trip on all three backends, shared conformance suite | 70/70 pg18 + 70/70 pg17 (postgres leg enforced); memory/sqlite legs inside the 15209-pass core run and the driver's 161-pass focused run |
| Append-only revisions; stale refused; one concurrent winner | `…append_only_with_one_cas_winner` + `…exactly_one_winner` executed on all three backends |
| Subgoal lineage + recorded ownership change | `…subgoal_lineage_preserves…` + `…agent_reassignment_is_an_explicit_recorded_transition` on all three backends |
| Run admission binding, immutable after admission | `test_run_goal_binding.py` in the 70/70 runs and the core run; upgraded-composition provenance read-back in the 26/26 |
| Two Workspaces isolated; foreign == missing | `…a_foreign_goal_answers_exactly_like_a_missing_one` + isolation tests on all three backends; authorization rides `maistro.workspaces.authorization` |
| Production composition + shipped Container | wiring source above; `test_goal_wiring.py` executed |
| No `GoalRun`/`OrchestratorRun`/second executor | grep empty; convergence freeze green at develop base |
| Migration identity / installed-base / upgrades | fresh 062→063 on both majors; live 26/26 both majors from real snapshots, no stamp edit, durable read-back |
| Restart durable composition, read back | `test_goal_restart_readback.py` in 70/70; PG upgraded-composition read-back in 26/26 |

## Sole remaining red — unchanged, external

`maistro.goals.model::GoalStatus` has no already-landed authorization on trusted base `4aa68edc0b6b` (develop head). Per the repo's two-merge rule this lane cannot land non-vulture grants; once the grant lands on develop, the gate and its two driving tests go green with no change here.

Disposition: all acceptance criteria re-proven first-hand at `f6777acd7` except that externally-owned prerequisite. No tree changes this round; no inventory delta (full 17-suite inventory matches the recorded baseline).
