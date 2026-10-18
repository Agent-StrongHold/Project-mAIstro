# #1572 repair round 3 — integration-scope legs proven first-hand at 23800125b

Round lane: `auto-1572` @ `23800125b15c2415b5e396a5dee48f04ea1b7bc2`,
develop base `0d49d4e068de` (merge base with develop: `d592654aca61`).

## Round brief and what it asked

The merge-queue evaluation named one failing gate: `integration-scope`. The
previous block was the round-2 worker's `BLOCKED` on the GoalStatus lifecycle
grant. This round re-proved every locally-runnable leg of the named gate and
re-confirmed the external blocker's state. `git fetch origin` this round:
`origin/develop` is still `0d49d4e068de` — **the grant has not landed**, so no
develop sync was possible or needed.

## The named gate, piece by piece (all first-hand at this head)

`integration-scope` has two halves: deterministic scope resolution, then a
CI-only poll of the required specialized legs.

1. Scope resolution (CI-exact inputs: `git diff --no-renames --name-only
   0d49d4e0...HEAD`, 76 paths):
   `scripts/ci_merge_group_scope.py --json <paths>` → EXIT 0,
   `scripts/check-integration-scope.py --event-name merge_group --scope-json
   ... --required-json` → EXIT 0; required set = exactly the nine legs below.
2. All nine required legs were then executed locally against this tree
   (containers dedicated to this round; no other lane's container touched):

| Required leg | Local execution at 23800125b | Result |
| --- | --- | --- |
| postgres (pg17) | full CI step sequence vs pgvector:pg17 (chain apply+reverse 17 passed, `alembic upgrade/downgrade/upgrade` clean, persistence 809, container wiring 15, workspaces 328 w/ PG legs, **goals 70 w/ `MAISTRO_REQUIRE_PG_LEGS=1`**, canvas 7, scheduling 311, hive scheduler 28) | **all green** |
| postgres (pg18) | same sequence vs pgvector:pg18 | **all green** |
| durable-events | `packages/maistro-core/tests/events` (383) + `tests/migrations/test_event_schema_agreement.py` (5), plain postgres:17, PG legs enforced | **388 passed** |
| strike-ladder | `tests/security/test_strike_tracker_conformance.py`, PG leg enforced | **40 passed** |
| wheel-imports | `uv build` all 12 wheels; `scripts/verify-wheel-imports.py --dist dist/ --python 3.12` EXIT 0; `scripts/verify-minimum-dependencies.py` EXIT 0 (all 12 deps at floors) | **green** |
| hive-conductor-e2e | `docker compose ... up --build --exit-code-from api-tests api-tests` (host port overridden 8101→18101; 8101 held by another lane's live container) | **exit 0** (10 passed / 13 skipped) |
| hive-conductor-e2e-ui | same with `--exit-code-from e2e-tests e2e-tests` | **exit 0, 161 passed** |
| object storage (MinIO) | pinned-release MinIO (`go install github.com/minio/minio@v0.0.0-20250422221226-0d7408fc9969`, EXIT 0) on 127.0.0.1:9000; `packages/maistro-core/tests/archive` | **128 passed** |
| docker-build | `docker build -f Dockerfile -t maistro-engine:test .` EXIT 0; examples-namespace assertion passes; engine booted on empty PG18 volume: `/health/live` and `/health/ready` OK, **`alembic_version` = `062`** | **green** |

The boot smoke doubles as production-composition evidence: the shipped engine
image, on a bare PostgreSQL 18 volume, migrates to `062_canonical_goals` and
reports ready — the `container.py:2365` `wire_goal_store` composition works in
the shipped artifact, not only in tests.

## Issue acceptance criteria — first-hand status at this head

- Goal/GoalRevision round-trip on all three backends: `test_goal_store_conformance.py`
  parametrized over memory/SQLite/PostgreSQL — **70 passed on pg17 and pg18**
  with legs enforced; memory/SQLite legs in the driver's run at this head
  (51 passed / 28 skipped, `check-3.log`).
- Append-only revisions, stale-refusal, one CAS winner:
  `test_goal_revision_chain_is_append_only_with_one_cas_winner`,
  `test_lifecycle_transitions_cas_and_terminal_is_final`,
  `test_concurrent_transitions_have_exactly_one_winner` — inside the 70.
- Subgoal lineage + explicit ownership transition:
  `test_subgoal_lineage_preserves_parent_goal_and_project`,
  `test_agent_reassignment_is_an_explicit_recorded_transition` — inside the 70.
- Run binding immutable after admission:
  `test_run_goal_binding.py` (binds, immutable, half-binding refused, a Run
  outcome never moves Goal state) — inside the 70.
- Two principals / two Workspaces; foreign Goal ≡ missing:
  `test_two_principals_cannot_reach_each_other_s_goals`,
  `test_a_foreign_goal_answers_exactly_like_a_missing_one` — inside the 70.
- Production composition: `container.py:2365` wires `goal_store`; Hive
  (`backend/adapters/maistro_core.py:195`) and maistro-server
  (`main.py:344`) both go through `create_container`;
  `test_goal_wiring.py::test_container_exposes_the_goal_store_and_its_seam`
  and the image boot smoke above prove it.
- No second executor: `scripts/check-m1-convergence-freeze.py --base
  d592654aca` → EXIT 0, "no unapproved new architecture island".
- Migration identity / installed-base upgrades:
  `tests/migrations/test_goal_installed_base_upgrade.py` → **8 passed on pg17
  and pg18** (forward-upgrade of databases migrated by the real develop
  snapshots `c560d4c`/`4675101`/`66f3cea`, no stamp edit, data + planner
  indexes survive, Goal tables live, restart read-back of bound provenance);
  full `tests/migrations` → **165 passed, 0 skipped** on pg17; chain
  apply/downgrade/upgrade clean on both majors; fresh-install head = `062`.

## The one remaining red is unchanged and external

Re-run first-hand at this head:

- `uv run python scripts/check-execution-lifecycles.py` → EXIT 1, sole finding
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary ... no
  already-landed authorization`. `origin/develop` unchanged at `0d49d4e0`
  (fetched this round), branch diff on `quality/ratchet-authorizations.json`
  empty — the two-merge rule again: the grant must land on develop first;
  it cannot be created in this branch without the campaign's ledger-edit
  prohibition (the round's CI-repair exception covers only the vulture
  ledger, which is green: CI-exact `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
  EXIT 0, 1323→1323).
- `tests/test_check_execution_lifecycles.py` → 1 failed
  (`test_the_shipped_ledger_matches_the_shipped_code`), 28 passed — the same
  root cause wearing a test hat.
- ac-state local shortfall: unchanged environmental artifact (round-2 proof
  of byte-identical counters at base stands; CI Quality-gate log recorded
  44.2377% ≥ 43.8998 at 20a88c52c).

## Round-3 commands (summary)

Deterministic scope pair (EXIT 0/EXIT 0), the nine legs as tabled above,
`check-execution-lifecycles.py` (EXIT 1, external), `tests/
test_check_execution_lifecycles.py` (1 failed / 28 passed, same cause),
`check-vulture-baseline.py` CI-exact (EXIT 0), `check-m1-convergence-freeze.py
--base d592654aca` (EXIT 0), `tests/migrations` full suite on pg17 (165
passed), `test_goal_installed_base_upgrade.py` on pg17+pg18 (8+8 passed).
No test files were added or changed in this round, so the suite inventory is
untouched (driver's `check-suite-inventory.py` runs at this head: ok).

## Residual risk

Live CI state at this exact SHA was not observable from this environment;
every deterministic leg of the named gate is now proven locally, and the
round-2 read-only API evidence at 20a88c52c (all nine legs success) plus the
three-file behavior-invariant diff since (043 docstring, this doc family,
057s test rename) makes a branch-caused CI regression implausible. The only
known red anywhere remains the external GoalStatus grant.
