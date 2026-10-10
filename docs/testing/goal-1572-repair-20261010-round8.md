# #1572 repair round 8 — independent re-verification at af29fae9; sole red re-proven external, unchanged

Round lane: `auto-1572` @ `af29fae91477` (clean tree, no source change this
round). The prior attempt died on a provider timeout **after** its five driver
checks had already passed on this exact head (job
`f93d30e3625542cdb338fed56bf77a06`, `check-0.log` … `check-4.log`: sync ok,
`ruff check` ok, `ruff format --check` 3281 files, targeted goals pytest
161 passed / 28 skipped, `check-suite-inventory.py --suite
packages/maistro-core/tests` ok). This round re-proves every acceptance leg
first-hand rather than trusting either transcript, and re-evaluates the one
open red.

## The named CI gate failures, re-run at this head

- **`test` (merge-queue red): reproduced; cause is exactly the documented
  external grant.** `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-execution-lifecycles.py` → FAIL with a single finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization` (baseline base
  `1f328be96a5e`, candidate `af29fae91477`, 19 classified → 20 discovered).
  The root-suite self-check that reds the `test` job,
  `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_
  the_shipped_code`, fails on that same sole finding (1 failed, 28 passed).
  Mechanics re-read from source this round: `ratchet_provenance.
  load_authorizations` reads `quality/ratchet-authorizations.json` **from the
  base revision** (its docstring states the two-merge consequence verbatim),
  and the gate's `visible_at_base` credits only source that already existed at
  the base. `origin/develop` was fetched this round and is **unchanged at
  `1f328be96`**: it carries no `GoalStatus` classification in
  `quality/execution-lifecycles.json` (0 mentions) and no
  `execution-lifecycles` grant row for it (`git diff origin/develop --
  quality/ratchet-authorizations.json` is empty; the candidate ledger's DOMAIN
  classification is in-branch only). An in-branch grant is therefore both
  mechanically ineffective and prohibited. Closing this requires an
  owner-side, grant-only landing on develop, then re-queueing this branch.
  This single finding propagates to all three named reds: the `test` job
  (root suite self-check), the Quality gate's Pillar 7 step
  (`quality.yml:1541`), and the coverage-gate combine's root-suite producer
  step (same suite, same self-check).
- **Quality gate: everything but the item above is green first-hand.**
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (lane-brief argv) → EXIT 0, 1323 reviewed identities →
  1323 findings. `check-m1-convergence-freeze.py --base 1f328be96` → EXIT 0.
  `check-ac-state.py --run-tests --ratchet --mandate 1f328be96…` (quality.yml
  argv, live PG 18 at head 063) → EXIT 0. `mypy --strict
  packages/maistro-core/src` → EXIT 0 (787 files; needs the `bootstrap` extra
  synced — `uv sync --locked --extra dev --extra bootstrap` — otherwise the
  five `import-not-found` errors in `maistro/cli/_install.py` and
  `maistro/cli/_builders_tui.py` are a local-venv artifact, not branch code;
  proven by syncing the extra and re-running clean).
- **Coverage gate: the round-5 fix verified at the test level.**
  `uv run pytest tests/test_verify_wheel_imports.py -q` → 23 passed. The full
  multi-producer combine (coverage-unit + archive + postgres + seven
  non-publish producers) was not reproduced locally — it needs the full
  service stack; the GoalStatus self-check inside its root-suite producer is
  the same external red as above.

## Issue acceptance legs, executed first-hand at af29fae9

Live lane containers: `auto-1572-pg` (pgvector:pg18, port 55712) and
`auto-1572-pg17` (pgvector:pg17, port 55717). Env per leg:
`MAISTRO_REQUIRE_PG_LEGS=1`, `MAISTRO_TEST_PG_DSN` /
`MAISTRO_TEST_DATABASE_URL` at fresh per-leg databases.

CI's exact postgres-job sequence (ci.yml:349-390), on **pg18** then **pg17**:

1. `pytest tests/migrations/test_migration_chain.py` on an empty database:
   **18 passed** (both majors). Chain ends at single head `063`
   (`upgrade 062 -> 063, The canonical Goal store`).
2. `alembic upgrade head` → head `063`; `alembic downgrade base` +
   `alembic upgrade head` → reversible (both majors).
3. `pytest packages/maistro-core/tests/goals` (PG legs required):
   **70 passed** per major — three-backend conformance (memory/sqlite/
   postgres: round-trip, append-only revisions with stale-revision refusal,
   lifecycle CAS with terminal-is-final, concurrent transitions with exactly
   one winner, Subgoal lineage preserving parent Goal and Project, agent
   reassignment as a recorded transition, missing-Goal semantics, two
   principals in two Workspaces isolated, foreign Goal ≡ missing Goal, full
   seam drive), Run admission binding `goal_id`/`goal_revision` immutable
   after admission (+ no-goal leaves it unset), restart readback, Container
   wiring (migrated pool and bare-database bring-up), and migration-063 ↔
   ensure-schema catalogue agreement.
   Procedure note: the conformance PostgreSQL leg requires a **migrated**
   DSN (its own skip message says so); pointing it at a bare database fails
   with `relation "canonical_goals" does not exist`, and one leg
   (schema agreement) then creates the tables, which is why a lone test
   re-run afterwards passes. CI's ordering (migrate, then the goals step)
   is the supported invocation and is what was executed here.
4. `pytest tests/migrations` (full suite, fresh DB per major):
   **168 passed** per major — including the installed-base upgrade fixtures
   built from the actual pre-Goal develop snapshots (`c560d4c` through
   user-model `056`, `4675101` through planner `057`, HITL `061`)
   forward-upgrading to the `063` head with no restamp, plus fresh-install,
   single-head, downgrade-refusal and reapplication coverage.
5. `pytest packages/maistro-core/tests/workspaces` (PG legs): **329 passed,
   2 skipped** per major; `pytest
   packages/maistro-core/tests/events/test_container_pg_durable_events.py`:
   **7 passed** per major (Container wiring composes `goal_store` +
   `goal_reader` in production shape).

No-source-change legs: `ruff check .` → all checks passed; `ruff format
--check .` → 3281 files; `check-suite-inventory.py` (bare) → 17/17 suites
match; `pytest tests/test_check_merge_markers.py` → 9 passed.

## Acceptance disposition (unchanged in kind from round 7; re-proven here)

| Criterion | Evidence this round |
| --- | --- |
| Goal/GoalRevision round-trip, three backends, shared conformance suite | 70 passed per major (pg17 + pg18) with PG legs forced; memory/sqlite legs in the same parametrized suite (driver check-3: 161 passed / 28 skipped at this head). |
| Append-only revisions, stale-revision refusal, single CAS winner | Same suite, executed per major. |
| Subgoal lineage preserves parent/Project; agent reassignment recorded | Same suite, executed per major. |
| Run admission binds goal_id/goal_revision, immutable after admission | `test_run_goal_binding.py` PG legs executed per major. |
| Two principals isolated; foreign Goal = missing Goal | Same suite, executed per major. |
| Production composition wires the store; shipped Container exposes it | `container.py` composes `goal_store` + `goal_reader`; durable-events Container test 7 passed per major; wiring suite green. App-level consumers are the unblocked issues (#805/#806/#1823) by design. |
| No second executor (`check-m1-convergence-freeze.py`) | EXIT 0 vs base `1f328be96`. |
| Migration identity: merged 056/057 preserved, Goal appends on integrated head under unused id | Goal = `063` after develop's `062`; single head asserted by the chain suite (18 passed per major). |
| Installed-base upgrade from actual develop snapshots, no restamp | 168 migration tests pass per major, fixtures from `c560d4c`/`4675101`/HITL `061`. |
| Fresh-install, single-head, downgrade/refusal, reapplication; both majors | Executed on pg17 + pg18. |
| Restart a durable composition and read back Goals/revisions/bound Run provenance | `test_goal_restart_readback.py` and the wiring readback legs, executed per major with PG legs forced. |

## Remaining blocker (unchanged in kind, third consecutive re-proof)

The merge-queue `test` job and the Quality gate's execution-lifecycles step
red on exactly one finding: `maistro.goals.model::GoalStatus` needs an
`execution-lifecycles` authorization row landed on develop **before** this
branch (two-merge rule; the ratchet reads authorizations from the merge base,
so an in-branch grant is mechanically ineffective and prohibited).
`origin/develop` was fetched this round and carries neither the grant nor the
classification. Every other named-gate leg re-proven this round is green at
`af29fae9`.

## Handoff

**BLOCKED** on the external GoalStatus authorization prerequisite, as in
rounds 6 and 7 — with this round's full acceptance battery re-executed
first-hand on both supported PostgreSQL majors so the next round inherits
current, not historical, evidence. No pushes, no GitHub mutations, no
destructive git operations; lane containers `auto-1572-pg` (pg18, port
55712) and `auto-1572-pg17` (port 55717) are left running with throwaway
databases (`goals_r8a`, `goals_r8a2`, `ci18_r8`, `mig18_r8`, `ci17_r8`,
`mig17_r8`, `goals_r8b`) for the next round.
