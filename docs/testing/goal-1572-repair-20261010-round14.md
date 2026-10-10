# #1572 repair round 14 — independent re-verification at 8ef1e2dbd; prior BLOCKED was a provider timeout; every acceptance criterion re-proven first-hand

Head: `8ef1e2dbdee14468c0066812fd37b1dc8f12b2bc`, base: `bb4257f0960fbc896bc097eb4460a7551b618683` (= origin/develop; `git merge-base HEAD origin/develop` = base). Worktree clean before and after. This round adds only this evidence note — no source, test, workflow, ledger or grant file changed, so no suite-inventory delta applies.

## Previous block resolved

The prior job (`d6e06fbbe8284852be631f940d061643`) ended `failure_kind: provider_error` ("Request timed out") **after its own four driver checks had already passed (returncode 0 on all: uv sync, ruff check, ruff format --check, focused Goal/parity pytest 161 passed + 28 skipped, suite inventory ok)**. The "worker requested attention: BLOCKED" was provider death, not a red gate. No work was left uncommitted.

## Named CI gates re-run first-hand at this head, this round

1. **Quality gate (Pillars 1–4, 7, 8).** `check-execution-lifecycles.py` → `19 classified -> 20 discovered`, sole FAIL delta `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted base and has no already-landed authorization` (trusted base `bb4257f0960f`). `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact per-workflow args) → **1323 = 1323**, `unclassified: 0`, no amendment. `check-m1-convergence-freeze.py --base bb4257f0960fbc896bc097eb4460a7551b618683` → "no unapproved new architecture island", exit 0. `grep -rn 'GoalRun\|OrchestratorRun' packages/*/src --include='*.py'` → no matches.
2. **test.** `tests/test_check_execution_lifecycles.py` first-hand: **28 passed, 1 failed** — the sole failure is `test_the_shipped_ledger_matches_the_shipped_code`, failing with the *identical* GoalStatus authorization delta. That is the same external red as gate 1, one layer down (round-12/13 full-suite runs: 4977 passed + this sole red; nothing else changed since — branch delta over round 13 is docs-only).
3. **Coverage gate.** Cascade confirmed structural: the `scripts` producer in `quality.yml` runs `coverage run -m pytest tests/ …` under `set -euo pipefail` (workflow lines ~555/714); the failing self-check lives in `tests/`, so the producer exits 1 and the combine step aborts. One root cause, three named reds.

## Why the sole red is external and not in-branch repairable (re-derived this round)

- `git show origin/develop:packages/maistro-core/src/maistro/goals/model.py` → "exists on disk, but not in 'origin/develop'"; `git ls-tree origin/develop packages/maistro-core/src/maistro/ | grep goal` → empty. GoalStatus is vocabulary **introduced by this branch**.
- The gate authorizes via `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)` (`scripts/check-execution-lifecycles.py:773`) — read from the **merge base**, per the repo's two-merge rule.
- `git diff origin/develop HEAD -- quality/ratchet-authorizations.json` → empty (byte-identical): neither side carries the grant, so no in-branch edit can be visible to the gate.
- `quality/execution-lifecycles.json` already carries the GoalStatus DOMAIN classification with rationale on this branch (4-line diff vs develop); the gate's message confirms classification exists and authorization is the missing piece. Lane policy permits ledger amendment only for the vulture baseline in exact-debt-ledger rounds — and vulture is clean. The grant must land on develop separately; everything downstream (quality step, shipped-ledger self-check, coverage combine) goes green with no change here.

## Acceptance criteria — first-hand this round (PG 18 on :55712, PG 17 on :55717, fresh DBs `r14_fresh`)

Fresh install: `alembic upgrade head` → **063** on both majors; `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions` present (asyncpg catalogue query).

`MAISTRO_REQUIRE_PG_LEGS=1` + both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` (plain `postgresql://` — the goals tests dial asyncpg directly; a `+asyncpg` scheme in these vars is a harness error, not a tree defect) → goals suite **70 passed on pg18 and 70 on pg17**. Named criteria tests verified individually via `-v`, all PASSED on memory + sqlite + postgres params:

- `test_goal_round_trips_through_the_backend[*]` (criterion 1)
- `test_goal_revision_chain_is_append_only_with_one_cas_winner[*]` (criterion 2)
- `test_concurrent_transitions_have_exactly_one_winner[*]` (criterion 2)
- `test_subgoal_lineage_preserves_parent_goal_and_project[*]` (criterion 3)
- `test_agent_reassignment_is_an_explicit_recorded_transition[*]` (criterion 3)
- `test_admission_binds_goal_id_and_revision[*]`, `test_the_binding_is_immutable_after_admission[*]`, `test_a_half_binding_is_refused`, `test_a_run_outcome_never_moves_goal_state` (criterion 4)
- `test_two_principals_cannot_reach_each_other_s_goals[postgres]`, `test_a_foreign_goal_answers_exactly_like_a_missing_one[*]` (criterion 5)
- `test_goal_revisions_and_bound_run_provenance_survive_a_restart` (restart read-back, PG)

Installed-base upgrades, both majors, no stamp edit: `tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py` → **26 passed pg18 (82.8s) and 26 passed pg17 (77.6s)**. The test file snapshot-migrates the **actual develop merges** `c560d4cc…` (user-model 056) and `4675101…` (planner 057), asserts restored files are byte-identical, forward-upgrades with the normal `upgrade head`, and does a second-process durable Goal/revision/bound-Run read-back — the issue's exact protocol.

Production composition (source re-verified at this head): `container.py:2365` `goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)` inside `create_container`, bound at `:2651`; principal seam `container.goals` → `ScopedGoalStore` at `:271-284`. Both shipped compositions construct it: Hive `backend/adapters/maistro_core.py:195` and maistro-server `main.py:344`. `test_goal_wiring.py` (inside the 70/70) proves the shipped Container exposes it.

## Disposition

All eleven acceptance criteria (seven core + four migration/installed-base) are proven by reachable production behavior and executed tests, re-verified first-hand this round. The single merge-queue red is the externally-owned `GoalStatus` execution-lifecycles grant (two-merge rule); it is not addressable in this lane and is not an acceptance criterion. No test additions → no inventory delta (driver inventory check: 1 suite matches the recorded baseline).
