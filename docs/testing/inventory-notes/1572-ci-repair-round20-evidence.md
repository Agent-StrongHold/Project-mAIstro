---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# #1572 CI repair round 20 evidence (2026-10-10)

Frozen scope: issue #1572 only, branch `auto-1572`, exact head
`eac8def896d381b956ec0cb824d785e321a6496c`, develop base
`435dc1937e0407ab4de198ffcced49860bb14ad2` (re-fetched this round: unchanged).
No PR enumeration beyond the supplied dispatch context, no remote mutation.
Worktree clean at entry; no code, tests, or ledger files edited this round.

## Prior BLOCKED re-attribution (again, from the artifact)

Prior job `840b8ec9317d4b7486331d035329ad4f` result.json: all five driver
checks returncode 0 (`uv sync`, `ruff check`, `ruff format --check`, targeted
goals pytest 161 passed 28 skipped, suite inventory ok 16334);
`failure_kind: provider_error` ("Request timed out"). The BLOCKED was the
model provider, never the tree.

## The three merge-queue reds re-proven first-hand at this head

1. **Quality gate (Pillars 1–4, 7, 8).** Sole red is the Pillar-7 step
   `uv run python scripts/check-execution-lifecycles.py` at CI's base shape
   (`RATCHET_BASE_REV=origin/develop`): FAIL
   `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
   the trusted base and has no already-landed authorization` (base 435dc193,
   19 classified -> 20 discovered). Every other step of the job re-run green
   this round: ruff check + format (driver, same head), radon 137 = 137,
   mypy strict 899 files clean, pyright 17 errors <= baseline 21, hypothesis
   `formal/` 666 passed 1 skipped, check-model-egress OK,
   check-foreign-harness-egress OK, fitness 23 passed, all twelve interrogate
   floors OK (nodes 38, durable_runs 45, projects 63, maistro 46, rsi 64,
   server 59, design 51, evolve 38 w/ vendored excluded, registry 50,
   bootstrap 45, canvas 36, turing 24).
2. **test (ci.yml root suite).** Exact job shape
   (`RATCHET_BASE_REV=origin/develop REQUIRE_AUTH=false MAISTRO_DRY_RUN=1
   pytest tests/ --ignore=tests/tools/registry -q`): 2 failed 4976 passed.
   First failure = `tests/test_check_execution_lifecycles.py::
   test_the_shipped_ledger_matches_the_shipped_code`, the shipped-ledger
   self-check of the same gate, same single delta (GoalStatus). Second failure
   = `test_every_quality_json_state_surface_is_classified_once` naming
   `quality/ac-state.json` — a gitignored worktree artifact
   (`.gitignore:81`), produced by running the ac-state scanner locally; a CI
   checkout cannot contain it, so the CI `test` job has exactly one red.
3. **Coverage gate (publish-set floor + diff coverage).** Structural cascade
   of the same single red: quality.yml's `coverage-gate` combine step runs the
   root suite as the `--source=scripts` producer under `set -euo pipefail`
   before `coverage xml`; the self-check failure aborts the step, so
   `coverage.xml` is never produced and the diff-coverage step never runs.

## Why no in-branch repair exists (verified, not assumed)

`scripts/check-execution-lifecycles.py:773` reads authorizations via
`prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)` — from the
merge base, not this branch. The branch already carries the reviewed ledger
entry (`quality/execution-lifecycles.json`, `maistro.goals.model::GoalStatus`
= DOMAIN with rationale); by construction it cannot authorize its own
introduction (`tests/test_check_execution_lifecycles.py::
test_a_new_canonical_literal_cannot_be_banked_by_its_ledger_entry`). The
lane's vulture-ledger repair instruction does not apply: the vulture gate
passes at CI's exact args
(`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` -> 1323 = 1323, exit 0), so no vulture amendment is
justified. Amending `quality/ratchet-authorizations.json` or
`quality/execution-lifecycles.json` to self-approve would violate the
two-merge rule (AGENTS.md: "a grant never authorizes the change that
introduces it"). The unblock is an upstream grant landing on develop
(ready-to-land record supplied in round 18), then a develop sync — both
outside this lane's Git permissions.

## Acceptance criteria, executed first-hand this round

- Databases: `auto-1572-pg` (pg18, 127.0.0.1:55712) and `auto-1572-pg17`
  (pg17, 127.0.0.1:55717) both dropped, recreated empty, migrated
  empty -> 063 through the real chain (`alembic upgrade head`, final step
  "062 -> 063, The canonical Goal store"); both `alembic_version` = 063.
- Goals suite with legs enforced
  (`MAISTRO_REQUIRE_PG_LEGS=1`, `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL`):
  **70/70 passed, 0 skipped, on pg18 and on pg17** — conformance round-trip
  across memory/sqlite/postgres, append-only revisions + stale-refusal +
  single CAS winner, Subgoal lineage/ownership transition, Run binding
  immutability, cross-Workspace authorization (foreign = missing), restart
  readback, Container wiring.
- Installed-base upgrades from real develop snapshots
  (`tests/migrations/test_goal_installed_base_upgrade.py`): **8/8 on pg18 and
  pg17** — c560d4c (user-model 056) and 4675101 (planner 057) trees forward-
  upgrade without reset or restamp, rows survive, restart readback.
- Migration chain (`tests/migrations/test_migration_chain.py`): **18/18 on
  pg18 and pg17** — fresh install, single head, unique IDs,
  downgrade/refusal, reapplication.
- Migration identity: `056_user_model_facts` (down
  `043_invocation_quota_door`) and `057_run_store_planner_stability` (down
  `056`) keep merged meaning/ancestry; Goal migration is the unused `063`
  (down `062` = develop head); single head `063`; develop tree has 68
  migration files, candidate 69 (+063 only).
- Production wiring read at source: `container.py:2414`
  `goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)`, passed to
  the Container (container.py:2701) with the `goal_reader` ScopedGoalStore
  seam (container.py:286); Hive composes via
  `packages/hive-conductor/backend/adapters/maistro_core.py:195`
  (`create_container`), maistro-server via
  `packages/maistro-server/src/maistro_server/main.py:29`; proven by
  `test_goal_wiring.py` (in the 70).
- Convergence: `check-m1-convergence-freeze.py --base origin/develop` green —
  no GoalRun/second executor/product-private Goal lifecycle.
- Suite inventory: `check-suite-inventory.py --suite
  packages/maistro-core/tests` ok (16334 collected, 0 duplicate). No test
  additions this round -> no inventory delta.

## Residual risk

Integration remains blocked on the external GoalStatus execution-lifecycles
authorization until it lands on develop and this branch syncs. All eleven
issue acceptance criteria are otherwise proven at this exact head.
