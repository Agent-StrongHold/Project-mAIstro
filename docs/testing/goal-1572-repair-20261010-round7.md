# #1572 repair round 7 — develop sync (1f328be96) resolved; Goal migration renumbers 062 -> 063

Round lane: `auto-1572`. Entry state: starting head `bc0c20b9d` with an
unfinished in-progress merge of `origin/develop` (`1f328be96`, the #1712
audit-log pagination closeout) — all incoming work staged, two files left
with conflict markers
(`tests/migrations/test_capability_invocation_effect_index_migration.py`,
`tests/migrations/test_task_admission_generation_upgrade.py`), which is what
the driver's `ruff check` / `ruff format` checks tripped on. No prior-round
work was discarded; the merge was completed in place.

## The concrete collision the sync exposed, and the fix

Both sides claimed migration id `062`: the branch's `062_canonical_goals`
(#1572) and develop's incoming `062_audit_cursor_indexes` (#358/#1712). The
2026-10-06 clarification on #1572 fixes the resolution rule: merged
identities keep their meaning and ancestry; the Goal store appends after the
integrated develop head under a centrally coordinated, unused id. So the Goal
migration renumbers to **`063`** (`down_revision = "062"`, the audit cursor
indexes), preserving one linear head and develop's
`056`/`057`/`058`/`059`/`060`/`061`/`062` byte-for-byte. This is exactly the
installed-base criterion — not a filename/head-assertion edit: the upgrade
fixtures below drive real `c560d4c`/`4675101` databases through the new id.

Changed files (merge commit `02bea0df1`):

- `tests/migrations/test_capability_invocation_effect_index_migration.py` —
  conflicts resolved; chain chronicle continues 061 -> 062 (audit) -> 063
  (Goals); single-head assertion `["063"]`; `062`/`063` ancestry and
  file-name pins added.
- `tests/migrations/test_task_admission_generation_upgrade.py` — conflict
  resolved onto the base-driven stamped-head assertion.
- `alembic/versions/062_canonical_goals.py` -> `063_canonical_goals.py`
  (`revision = "063"`, `down_revision = "062"`, docstring updated).
- `tests/migrations/test_goal_installed_base_upgrade.py` —
  `GOAL_REVISION = "063"`, parent `062`, filename pin.
- `packages/maistro-core/tests/goals/test_goal_pg_schema_agreement.py` —
  `GOAL_REVISION_RANGE = "062:063"`, docstrings, class name.
- `packages/maistro-core/src/maistro/goals/pg_store.py`,
  `packages/maistro-core/src/maistro/goals/wiring.py`,
  `packages/maistro-core/src/maistro/container.py`,
  `packages/maistro-core/tests/goals/test_goal_wiring.py`,
  `packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py`,
  `packages/maistro-core/tests/events/test_container_pg_durable_events.py`,
  `tests/migrations/test_migration_chain.py`,
  `alembic/versions/043_invocation_quota_door.py` — migration-number
  references updated (comments/docstrings only; no behavior change).

No test was added or removed: `python scripts/check-suite-inventory.py`
(bare, CI's argv) passes with all 17 recorded suites matching, 31114 unique
identities, zero duplicates — so no inventory note is required this round.

## Executed validation (all `uv run`, live Docker pgvector containers owned by this lane)

- `git fetch origin develop`: unchanged at `1f328be96`; it contains neither a
  `GoalStatus` classification in `quality/execution-lifecycles.json` nor an
  `execution-lifecycles` authorization in `quality/ratchet-authorizations.json`.
- `uv run ruff check .` / `uv run ruff format --check .`: pass (3281 files).
- `uv run alembic heads`: single head `063`.
- `tests/migrations` on PostgreSQL 18.6 (pgvector:pg18),
  `MAISTRO_REQUIRE_PG_LEGS=1`: **168 passed** — including the installed-base
  upgrade fixtures built from the actual pre-Goal develop snapshots
  (`c560d4c` through user-model `056`, `4675101` through planner `057`, HITL
  `061`) forward-upgrading to the `063` head with no restamp, plus
  fresh-install, single-head, downgrade-refusal and reapplication coverage.
- `tests/migrations` on PostgreSQL 17 (pgvector:pg17), same env: **passed**
  (all 168; combined-run output shows the goals-suite errors below only).
- `packages/maistro-core/tests/goals` with PG legs forced, pg18: **70
  passed**; pg17: **70 passed** — three-backend conformance (round-trip,
  append-only revisions, stale-revision refusal, single CAS winner, Subgoal
  lineage preserving parent/Project, agent reassignment as a recorded
  transition, two principals in two Workspaces isolated, foreign Goal =
  missing Goal), Run binding (admission binds `goal_id`/`goal_revision`,
  immutable after admission), restart readback, Container wiring (migrated
  pool and bare-database schema bring-up), and migration-063 <->
  ensure-schema catalogue agreement.
  Note: running `tests/migrations` and the goals suite in ONE pytest
  invocation on the same database fails the goals legs — the migration
  suite's downgrade tests leave the shared database below head. CI runs them
  as separate steps (ci.yml:359 and ci.yml:389), where both are green; the
  interaction is pre-existing test hygiene, not a Goal-store defect.
- `tests/test_verify_wheel_imports.py`: 23 passed (coverage-gate leg from the
  round-5 fix, still green post-merge).
- `tests/test_check_merge_markers.py`,
  `packages/maistro-core/tests/events/test_container_pg_durable_events.py`,
  `packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py`:
  18 passed.
- `python scripts/check-suite-inventory.py` (bare): pass, 17/17 suites.
- `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: pass, 1323 reviewed identities = 1323
  findings; `git diff --numstat MERGE_HEAD -- quality/` shows only
  branch-side additions, no ledger rows lost.
- `python scripts/check-m1-convergence-freeze.py --base 1f328be96`: pass —
  no unapproved new architecture island (no GoalRun/second executor).
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-execution-lifecycles.py`:
  **FAIL — sole finding** `maistro.goals.model::GoalStatus: NEW work-state
  vocabulary is absent from the trusted base and has no already-landed
  authorization`; the root-suite self-check
  `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
  fails on that same sole finding (1 failed, 28 passed).

## Acceptance disposition

| Criterion | Evidence this round |
| --- | --- |
| Goal/GoalRevision round-trip, three backends, shared conformance suite | 70 passed per major (pg17 + pg18) with PG legs forced. |
| Append-only revisions, stale-revision refusal, single CAS winner | Same suite, executed. |
| Subgoal lineage preserves parent/Project; agent reassignment recorded | Same suite, executed. |
| Run admission binds goal_id/goal_revision, immutable after admission | `test_run_goal_binding.py` PG legs executed (both majors). |
| Two principals isolated; foreign Goal = missing Goal | Same suite, executed. |
| Production composition wires the store; shipped Container exposes it | `container.py` composes `goal_store` + `goal_reader`; `test_goal_wiring.py` and the durable-events Container test pass. App-level consumers are the unblocked issues (#805/#806/#1823) by design. |
| No second executor (`check-m1-convergence-freeze.py`) | Exit 0 vs base `1f328be96`. |
| Migration identity: merged 056/057 preserved, Goal appends on integrated head under unused id | **Fixed this round**: Goal = `063` after develop's `062`; single head; chain-walk test asserts full ancestry. |
| Installed-base upgrade from actual develop snapshots, no restamp | 168 migration tests pass per major, fixtures from `c560d4c`/`4675101`/HITL `061`. |
| Post-upgrade persistence/readback; existing data survives; reopen and read back | Same installed-base suite legs, executed per major. |
| Fresh-install, single-head, downgrade/refusal, reapplication; both majors | Executed on pg17 + pg18. pg17 CI matrix leg remains CI's own run. |

## Remaining blocker (unchanged in kind, re-proven at the merged head)

The merge-queue `test` job and the Quality gate's execution-lifecycles step
red on exactly one finding: `maistro.goals.model::GoalStatus` needs an
`execution-lifecycles` authorization row landed on develop **before** this
branch (two-merge rule; the ratchet reads `quality/ratchet-authorizations.json`
from the merge base, so an in-branch grant is mechanically ineffective and
prohibited). `origin/develop` was fetched this round and carries neither the
grant nor the classification. Closing it requires an owner-side grant-only
landing on develop, then re-queueing this branch. Every other named-gate leg
re-proven this round is green at the merged head `02bea0df1`.

## Handoff

**BLOCKED** on the external GoalStatus authorization prerequisite, as in
round 6 — but the round's assigned repair (the develop sync conflict and the
duplicate `062`) is complete, committed, and validated first-hand on both
supported PostgreSQL majors. No pushes, no GitHub mutations, no destructive
git operations; lane containers `auto-1572-pg` (pg18, port 55712) and
`auto-1572-pg17` (port 55717) are left running for the next round.
