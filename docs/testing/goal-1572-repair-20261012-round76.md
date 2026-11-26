# #1572 round-76 repair verification (2026-10-12)

Dispatch head `d8c32399b8bc3f5574ab6db6ca7d7b2a835e5e87`; base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Every item below was re-derived or re-executed first-hand this round; none is carried on trust.

## The one blocker (unchanged, external)

- `uv run python scripts/check-execution-lifecycles.py` at the exact CI argv
  (`.github/workflows/quality.yml:1541`) exits **1** with the single finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19 -> 20 discovered).
- `tests/test_check_execution_lifecycles.py` re-run: **1 failed / 28 passed**,
  same sole finding with gate-identical stdout — this is the merge-queue
  `test: failure`, 1:1 (the coverage `combine` step inherits the dead producer).
- `origin/develop` re-fetched: tip **unchanged**, == merge-base
  `3c761d14db94`, branch 177 commits ahead. `git grep GoalStatus origin/develop
  -- quality/` = no matches; develop's `execution-lifecycles` grants are exactly
  `services.rsi::RunStatus` + `agent_delegate_remote::DelegationStatus` (#1136).
- The branch's `quality/ratchet-authorizations.json` is byte-identical to
  develop (`git diff origin/develop HEAD -- quality/ratchet-authorizations.json`
  = 0 lines), so re-adding the grant in-branch is a proven no-op:
  `load_authorizations` (`scripts/ratchet_provenance.py:478-495`) reads grants
  **from the base revision**; its docstring states the consequence verbatim —
  "a new grant does not take effect in the change that introduces it.
  Authorizing a floor-raise is now two merges". The candidate already
  classifies `GoalStatus` DOMAIN (`quality/execution-lifecycles.json:89`);
  self-classification does not authorize.
- Captured GitHub state (dispatch-context.json, 95 sources through
  2026-10-12T17:19:01Z): PR #1938 (grant-only) **open, not merged**, head
  `2f5dd46969fc`; newest issue comments are `maistro-progress` bot markers only;
  issue still open. No maintainer grant exists anywhere landed.
- No in-branch repair exists: renaming/removing `GoalStatus` would violate the
  issue-mandated lifecycle (active/satisfied/cancelled/failed/superseded) or
  dodge the `_MIN_WORK_STATES=3` detector (prohibited weakening);
  `RATCHET_BASE_REV=HEAD` self-reference is refused by
  `_refuse_self_reference`. Round-74's plumbing simulation stands: once the
  grant lands on develop, this branch's gate passes with zero branch edits.

## Lane-brief vulture CI-repair exception: no target

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (exact argv,
`quality.yml:1076-1081`): **exit 0**, 1323 reviewed identities -> 1323
findings, `never_allowlist: 0`. Nothing is unbanked; there is no identity to
fix or amend.

## Acceptance re-executed this round

Fresh databases this round on **both supported majors**: pg18 `r76g18`
(server 18.6, port 5433) and pg17 `r76g17` (server 17.11, ephemeral container,
removed after the run).

- **Fresh install / single head (both majors):** `alembic upgrade head` exit 0
  from empty, final step `062 -> 063, The canonical Goal store`; `alembic heads`
  = `063 (head)` single; exactly 3 `canonical_goal*` tables
  (`canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions`);
  `alembic_version` stamp `063` on both majors.
- **Migration ancestry preserved (source-read):**
  `056_user_model_facts.py:43-44` `revision="056"`,
  `down_revision="043_invocation_quota_door"` (merged identity c560d4c);
  `057_run_store_planner_stability.py:96-97` `revision="057"`,
  `down_revision="056"` (merged identity 4675101);
  `063_canonical_goals.py:53-54` `revision="063"`, `down_revision="062"` —
  appended after the integrated develop head under a centrally coordinated,
  previously unused identity.
- **Goal acceptance (both majors):**
  `uv run pytest packages/maistro-core/tests/goals -q` with
  `MAISTRO_REQUIRE_PG_LEGS=1` + both DSNs: **70 passed / 0 failed / 0 skipped**
  on pg18 and pg17. Criterion map (all parameterized `[memory, sqlite,
  postgres]` unless noted): conformance round-trip (AC1);
  `test_goal_revision_chain_is_append_only_with_one_cas_winner`,
  `test_lifecycle_transitions_cas_and_terminal_is_final`,
  `test_concurrent_transitions_have_exactly_one_winner` (AC2);
  `test_subgoal_lineage_preserves_parent_goal_and_project` +
  `test_agent_reassignment_is_an_explicit_recorded_transition` (AC3);
  `test_run_goal_binding.py` immutable admission binding (AC4);
  `test_two_principals_cannot_reach_each_other_s_goals` with foreign==missing
  (`test_missing_goal_is_goal_not_found_on_every_read`, AC5);
  `test_goal_wiring.py` shipped-Container exposure (AC6);
  `test_goal_pg_schema_agreement.py` migration DDL == ensure-schema (6 tests);
  `test_goal_restart_readback.py::test_goal_revisions_and_bound_run_provenance_
  survive_a_restart` (durable restart readback).
- **Full migration battery:** `uv run pytest tests/migrations -q` with
  `MAISTRO_TEST_DATABASE_URL`/`MAISTRO_TEST_PG_DSN`/`DATABASE_URL` exported:
  **168 passed / 0 skipped / 0 failed** — includes
  `test_migration_chain.py` (single head, unique IDs, quota-door ancestry),
  `test_goal_installed_base_upgrade.py` (forward upgrades from the actual
  pre-Goal develop snapshots c560d4c/4675101 with no stamp edit, populated
  data surviving), and downgrade/refusal/reapplication coverage.
- **Direct downgrade round-trip (pg18 r76g18):** `alembic downgrade 062` exit 0
  drops `canonical_goal*` 3 -> 0, stamp `062`; `alembic upgrade head` exit 0
  re-creates 0 -> 3, stamp `063`.
- **Convergence freeze (AC7):** `uv run python
  scripts/check-m1-convergence-freeze.py --base 3c761d14db944a727fa0744444bc67c
  fe36d49f7` (CI argv, `formal-conformance.yml:70-78`) **exit 0**; no
  `GoalRun`/`OrchestratorRun` anywhere in `packages/*/src`.
- **Production composition (source-read):** `container.py:42-44` imports,
  `:268-273` `goal_store` field, `:276-286` `goal_reader` -> `ScopedGoalStore`
  seam, `:2412-2414` `await wire_goal_store(db_pool, pg_pool=pg_pool)` inside
  `create_container`; `maistro_server/main.py:29` imports `create_container`
  and composes it (~line 344); hive
  `backend/adapters/maistro_core.py:148` imports and ~line 195 composes it —
  both shipped compositions (Hive, maistro-server) get the store through the
  container, not tests-only.
- **Driver checks at this head** (job check-*.log): sync ok, ruff check "All
  checks passed!", format "3288 files already formatted", root suite
  `161 passed, 28 skipped`, suite inventory ok (`16334` identities, 0
  duplicates).
- **mypy:** `uv run mypy packages/*/src` per AGENTS.md — **Success: no issues
  found in 899 source files**.

## Verdict

**BLOCKED** — unchanged and external. The sole CI failure is the
execution-lifecycles floor raise for `maistro.goals.model::GoalStatus`, which
by the two-merge rule can only be authorized by a grant already landed on
develop (grant-only PR #1938, open/unmerged). Once that grant is merged, this
branch's gate and shipped-ledger test pass with zero branch edits (demonstrated
by round-74's plumbing simulation; re-derived from source this round). The
lane-brief vulture-ledger amendment exception has no target (gate exit 0).
Docs-only round: no code, test, or ledger changes; no inventory delta.
