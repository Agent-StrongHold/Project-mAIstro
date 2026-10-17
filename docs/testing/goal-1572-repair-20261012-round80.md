---
issue: 1572
round: 80
head: 0ff5facee6ebdac323bc0f04316bb8df3a86782c
base: 3c761d14db944a727fa0744444bc67cfe36d49f7
date: 2026-10-12
verdict: BLOCKED
blocker: external maintainer execution-lifecycles grant for maistro.goals.model::GoalStatus (grant-only PR #1938, open head 2f5dd46969fc)
inventory-delta: none (docs-only round; no tests added, removed, or changed)
---

# Round 80 repair verification (issue #1572) — every claim re-executed first-hand this round

Nothing in this file is carried from an earlier round's word; each line cites a
command run or source read at HEAD `0ff5facee` during this round. Driver logs
(`check-0..4.log`: `uv sync --locked --extra dev` ok, `ruff check .` "All
checks passed!", `ruff format --check .` 3288 files, pytest 161 passed/28
skipped, suite inventory ok 16334) are green at this exact head.

## 1. The block, re-proven (still standing)

- **Gate at exact CI argv** (`.github/workflows/quality.yml:1541`
  `uv run python scripts/check-execution-lifecycles.py`): **exit 1**, sole
  finding `maistro.goals.model::GoalStatus: NEW work-state vocabulary is
  absent from the trusted base and has no already-landed authorization`
  (19 classified -> 20 discovered).
- **The merge-queue `test: failure`, 1:1**:
  `uv run pytest tests/test_check_execution_lifecycles.py` = **1 failed /
  28 passed**; the failing test
  `test_the_shipped_ledger_matches_the_shipped_code` invokes the gate `main()`
  and its captured stdout is byte-identical to the gate run above.
- **origin/develop re-fetched and unchanged**: tip `3c761d14db94` ==
  merge-base (nothing to sync or merge);
  `git grep GoalStatus origin/develop -- quality/` -> no matches (exit 1);
  `git diff origin/develop HEAD -- quality/ratchet-authorizations.json` ->
  empty (the branch's grant file is byte-identical to develop, so an in-branch
  grant is a proven no-op);
  `git ls-remote` -> develop `3c761d14db94`, `refs/pull/1938/head`
  `2f5dd46969fc` (grant-only PR still open, unmerged, head unchanged).
- **Two-merge rule re-read from source**:
  `scripts/ratchet_provenance.py:478-503` — `load_authorizations` reads grants
  **from the base revision**; docstring verbatim: "a new grant does not take
  effect in the change that introduces it. Authorizing a floor-raise is now
  two merges -- the grant, then the regression it permits." The gate reads the
  same way: `scripts/check-execution-lifecycles.py:758` `resolve_baseline`,
  `:773` `load_authorizations(RATCHET, base=trusted_ref.base_sha)`,
  `:784` `_unauthorized_additions`.
- **Classification is not the defect**: the candidate ledger already
  classifies the vocabulary (`quality/execution-lifecycles.json:89-92`,
  DOMAIN with rationale, "Deliberately not execution state ... a Goal never
  drives a scheduler"). The gate still fails because the *grant* must be
  already-landed at the base, and develop has zero GoalStatus grants.
- **No in-branch repair exists**:
  - Removing or renaming `GoalStatus` would delete the issue-mandated Goal
    lifecycle ("e.g. active, satisfied, cancelled, failed, superseded") or
    dodge the `_MIN_WORK_STATES` detector — gate-weakening, prohibited.
  - Dropping the ledger row fails `audit()` (discovered-but-unclassified).
  - `RATCHET_BASE_REV=HEAD` is refused by `_refuse_self_reference`.
  - The rounds-74/77 executed simulation (develop+grant base -> gate exit 0
    with zero branch edits) carries over; the mechanism it demonstrated is
    re-read from source this round (points above).
- **Lane-brief vulture CI-repair exception has NO target**:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact CI argv) -> **exit
  0**, `1323 reviewed identities -> 1323 findings`, `never_allowlist: 0`.
  There is no unbanked identity to fix and no reviewed-retained identity to
  amend into `quality/vulture-baseline.json`.

## 2. Acceptance criteria, re-executed this round

Environment: two fresh Postgres containers this round — `r80g18`
(pgvector/pgvector:pg18, host port 54329) and `r80g17` (pg17, port 54331);
goals legs run with `MAISTRO_REQUIRE_PG_LEGS=1` (turns a missing PG leg into a
failure, not a skip) and both `MAISTRO_TEST_PG_DSN` and
`MAISTRO_TEST_DATABASE_URL` set (plain `postgresql://`).

- **AC1 Goal/GoalRevision round-trip on all three backends** —
  `uv run pytest packages/maistro-core/tests/goals -q` with
  `MAISTRO_REQUIRE_PG_LEGS=1`: **70 passed / 0 failed / 0 skipped** on pg18
  (fresh DB migrated empty->063 first) **and on pg17** (re-run after its
  battery migrated the DB; see operator artifact below).
  `test_goal_round_trips_through_the_backend[memory|sqlite|postgres]` all ran.
- **AC2 append-only, stale refused, one CAS winner, terminal-final** —
  `test_goal_revision_chain_is_append_only_with_one_cas_winner[*]`,
  `test_lifecycle_transitions_cas_and_terminal_is_final[*]`,
  `test_concurrent_transitions_have_exactly_one_winner[*]` — passed on all
  three backends.
- **AC3 subgoal lineage + explicit recorded agent transition** —
  `test_subgoal_lineage_preserves_parent_goal_and_project[*]`,
  `test_agent_reassignment_is_an_explicit_recorded_transition[*]` — passed.
- **AC4 Run binding immutable after admission; outcome never moves Goal state**
  — `test_admission_binds_goal_id_and_revision[*]`,
  `test_the_binding_is_immutable_after_admission[*]`,
  `test_a_run_outcome_never_moves_goal_state`,
  `test_a_half_binding_is_refused` — passed.
- **AC5 two-principal isolation; foreign Goal == missing Goal** —
  `test_two_principals_cannot_reach_each_other_s_goals[*]`,
  `test_a_foreign_goal_answers_exactly_like_a_missing_one[*]` — passed.
- **AC6 production composition** — source-read this round:
  `packages/maistro-core/src/maistro/container.py:44` imports
  `wire_goal_store`, `:273` `goal_store` field, `:276-286` `goal_reader`
  `ScopedGoalStore` seam, `:2414` `wire_goal_store(...)` inside
  `create_container`; maistro-server `main.py:29` imports `create_container`,
  `:344` calls it in production startup; Hive
  `packages/hive-conductor/backend/adapters/maistro_core.py:148` imports
  `create_container`, `:195` builds the embedded Container from the same
  composition. Tests `test_container_exposes_the_goal_store_and_its_seam`,
  `test_goal_reader_rides_the_container_end_to_end` — passed.
- **AC7 no second executor / product-private lifecycle** —
  `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db94` (CI argv, `formal-conformance.yml:77`) -> **exit 0**;
  `grep -rn "GoalRun\|OrchestratorRun" packages/*/src/` -> no matches (exit 1).
- **Migration identity preserved** — `alembic upgrade head` on the fresh pg18
  DB ran empty->063 as a single chain, final line `062 -> 063, The canonical
  Goal store`, with `057 -> 058` in the log proving merged user-model `056`
  (`c560d4c`) and planner `057` (`4675101`) identities kept their meaning and
  ancestry; `alembic heads` = `063 (head)`, `alembic current` = 063, and all
  three tables `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions` exist (`pg_tables` query); same stamp/tables
  verified on pg17 after its battery.
- **Installed-base + chain + downgrade coverage (both majors)** —
  `uv run pytest tests/migrations -q` against each fresh major: **168 passed /
  0 failed / 0 skipped on pg18 and on pg17** (3m27s / 3m25s).
  `tests/migrations/test_goal_installed_base_upgrade.py:58-59` pins the real
  develop merge SHAs `c560d4ccad82...` and `4675101647e6...`, builds actual
  snapshot trees, inserts installed-base rows, forward-upgrades without
  touching the stamp, and asserts rows survive; downgrade/refusal/
  reapplication legs present (`:181`, `:186`).
- **Restart readback** —
  `test_goal_revisions_and_bound_run_provenance_survive_a_restart` — passed.
- **Schema agreement (migration 063 == ensure_schema)** — 6 tests in
  `test_goal_pg_schema_agreement.py` — passed.
- **Types** — `uv run mypy packages/maistro-{core,server,turing,canvas,
  bootstrap,registry,ext-sdk}/src` -> "Success: no issues found in 899 source
  files".

### Operator artifact recorded this round (pg17 leg ordering)

Running the goals suite against a **not-yet-migrated** pg17 DB produced 3
errors in `test_run_goal_binding.py[postgres]` — the documented empty-DB
artifact (`test_run_goal_binding.py:58-65` requires a migrated database).
After the migration battery migrated that DB, the same suite passed 70/70.
Not a branch defect; the pg18 leg ran migration-first and was green on the
first pass.

## 3. Verdict

**BLOCKED** — on the external maintainer execution-lifecycles grant for
`maistro.goals.model::GoalStatus`. Every acceptance criterion of issue #1572
is proven above at this head; the sole failing CI leg (merge-queue `test:
failure`) is the shipped-ledger test, which fails only because the grant that
authorizes the new lifecycle vocabulary must land on develop first
(two-merge rule, `ratchet_provenance.py:494-496`). Merging grant-only PR
#1938 makes the gate and the test pass with **zero branch edits** (executed
simulation, rounds 74/77; mechanism re-read from source this round).

No code, test, or ledger files were changed this round; docs-only.
