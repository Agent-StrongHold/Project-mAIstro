# #1572 repair round 13 — develop sync (bb4257f09) with a real pg_store conflict resolved; all three named CI reds traced to their one external root cause

Head: `fd20f0eb7f8e6e0ccd3fa9b998605ca29e5a4d4c` (merge of `origin/develop` `bb4257f0960f` into `c2bf8294e36a`), base after sync: `bb4257f0960f` (develop head is now an ancestor of this branch; `git merge-base HEAD origin/develop` = `bb4257f0960f`). Worktree clean before and after.

## Develop sync (dispatch-mandated)

`git fetch origin` → origin/develop advanced `4aa68edc0` → `bb4257f09`: two commits, #2115 "Prepare validated PG root Runs before transaction acquisition" (`d11368cd7`) and #2114 "Reuse PG Run insertion inside caller transaction" (`bb4257f09`). Delta: `packages/maistro-core/src/maistro/runs/pg_store.py` (130 lines), two new ADRs (1882-pg-root-preparation-seam, 1883-pg-run-insert-connection), two new test files (`test_pg_root_preparation.py`, `test_pg_run_insert_connection.py`), and their inventory notes. **No `quality/` changes on develop** — in particular no `ratchet-authorizations.json` row.

Merge produced exactly one conflict: `packages/maistro-core/src/maistro/runs/pg_store.py` — develop's root/child split of `create_run` vs this branch's `goal_id`/`goal_revision` admission parameters. Resolution (commit `fd20f0eb7`):

- `create_run` routes parentless admissions to `prepare_root_run` and children to `prepare_run`, both now carrying `goal_id`/`goal_revision`.
- `prepare_root_run` gains the two parameters and applies them in its `Run(...)` construction — a root Run binds its Goal through the new seam without losing the #1882 connection-releasing ordering.
- `prepare_run`'s parentless delegation forwards the binding (the task-run admitter, `tasks/admission.py:286`, enters here — exercised by the tasks admission tests inside the 15209-pass core leg).
- Goal fields persist inside the Run `payload` JSONB (`json_of(run)`), so no INSERT or schema change was needed.

## Named CI gates, re-run first-hand at this content

The three merge-queue failures at `c2bf8294e36a` share **one** root cause. Evidence per gate:

1. **Quality gate (Pillars 1–4, 7, 8).** Sole failing step: `check-execution-lifecycles.py` → `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted base and has no already-landed authorization` (now against trusted base `bb4257f0960f`). All other named steps green at this head: `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **1323 = 1323**, no amendment; `check-m1-convergence-freeze.py --base 4aa68edc0` → green; `check-model-egress.py` → green; `check-foreign-harness-egress.py` → exit 0; `check-reachability.py` → exit 0; `check-radon-baseline.py` → **137 = 137**; xenon (CI's exact scope) → **139 block ≤ 145 baseline, 0 module, average ok**; ruff check + format check (3283 files) → clean; mypy `packages/maistro-core/src` → only the 5 pre-existing `maistro_bootstrap` import-not-found notes (dev extra does not install that member; zero errors in `runs/`); full `check-suite-inventory.py` → **ok, 17 suite(s), 31147 unique nodes, 0 duplicates**.
2. **test.** Root tree `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 pytest tests/ --ignore=tests/tools/registry -q` → **1 failed, 4976 passed, 136 skipped** (271.6s); the 1 is `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`, which asserts `gate.main() == 0` — the same missing authorization. Producer legs: core **15209 passed** (243s), server/ext **1837 passed**, hive **3625 passed** — all matching round 12 exactly.
3. **Coverage gate (publish-set floor + diff coverage).** Its `combine` step re-runs the root suite as the `scripts` producer (`coverage run … -m pytest tests/ …`) under `set -euo pipefail`; the failing GoalStatus gate self-check makes that producer exit 1 and aborts the step — the same external red, one cascade deeper. The three upstream producers (`coverage (no services)`, `(MinIO)`, `(PostgreSQL)`) all **succeeded** on CI at `c2bf8294e36a`, so no floor/diff regression exists behind the cascade. Post-merge diff-coverage exposure is limited to the conflict-resolution lines: every added line executes on ordinary admissions — root/child kwargs in `create_run` (all suites), `prepare_root_run` body (10/10 new PG tests passed with legs enforced, both majors), and `prepare_run`'s parentless delegation (task admissions, `tasks/admission.py:286`).

## The single remaining red, and why it is not in-branch repairable

`maistro.goals.model::GoalStatus` is classified DOMAIN with rationale in `quality/execution-lifecycles.json` on this branch, but the gate reads authorizations from the **merge-base commit** (`scripts/check-execution-lifecycles.py:773`, `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`), and `quality/ratchet-authorizations.json` is **byte-identical between this branch and develop** — neither carries the row. This is the repo's two-merge rule ("candidate baseline edits cannot approve them"): the grant must land on develop in a separate change before this PR's gate can pass. In-branch amendment of the authorization file is mechanically invisible to the gate. Everything downstream of that one row — the quality-gate step, its shipped-state self-check in `tests/`, and therefore the coverage combine — is green the moment it lands, with no change here.

## PostgreSQL legs at this head (first-hand, both majors)

Fresh databases `r13_fresh` in `auto-1572-pg` (:55712, pg18) and `auto-1572-pg17` (:55717, pg17); `alembic upgrade head` → `063` with `canonical_goals` / `canonical_goal_revisions` / `canonical_goal_transitions` on both.

- `MAISTRO_REQUIRE_PG_LEGS=1 … pytest packages/maistro-core/tests/goals -q` → **70 passed** on pg18 **and** 70 on pg17 (includes the three-backend conformance suite with append-only/CAS, subgoal lineage, ownership transition, foreign-goal indistinguishability, and `test_run_goal_binding.py` — which now exercises the merged `prepare_root_run` goal-binding path on PostgreSQL).
- Develop's new PG tests with legs enforced → **10 passed** on pg18 and 10 on pg17 (the #1882/#1883 semantics survive the conflict resolution).
- `tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py` against `r13_fresh` → **26 passed** on pg18 (75s) and 26 on pg17 (77s): live upgrades from the real develop snapshots with no stamp edit, plus the durable-composition Goal/revision/bound-Run read-back.

## Disposition

All acceptance criteria remain proven first-hand (round-12 map unchanged; this round's delta re-verified where the merge touched it: Run admission binding through the new root seam). The sole blocker is the externally-owned `GoalStatus` execution-lifecycles grant. No test additions by this round → no inventory delta (full inventory matches the recorded baseline).
