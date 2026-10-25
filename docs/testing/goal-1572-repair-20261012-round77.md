# #1572 round-77 repair verification (2026-10-12)

Dispatch head `f4efdee21bfdf93283d2e0806cf17776baba21e1`; base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Every item below was re-derived or
re-executed first-hand this round; none is carried on trust from round 76 or
from the drifted prior MERGE-READY artifact.

## The one blocker (unchanged, external)

- `uv run python scripts/check-execution-lifecycles.py` at the exact CI argv
  (`.github/workflows/quality.yml:1541`) exits **1** with the single finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19 -> 20 discovered).
- `tests/test_check_execution_lifecycles.py` re-run: **1 failed / 28 passed**,
  same sole finding with gate-identical stdout — this is the merge-queue
  `test: failure`, 1:1 (the coverage `combine` step inherits the dead producer).
- `origin/develop` re-fetched this round: tip **unchanged**, ==
  merge-base `3c761d14db94`, branch 178 commits ahead. `git grep GoalStatus
  origin/develop -- quality/` = 0 matches: no grant has landed.
- The branch's `quality/ratchet-authorizations.json` has a **0-line diff**
  against develop, so an in-branch grant re-add is a proven no-op AND is outside
  this round's permitted amendment scope. Mechanics re-derived from source:
  `load_authorizations` (`scripts/ratchet_provenance.py:478-495`) reads grants
  **from the base revision** — docstring verbatim: "a new grant does not take
  effect in the change that introduces it. Authorizing a floor-raise is now two
  merges". The gate calls it with `base=trusted_ref.base_sha`
  (`check-execution-lifecycles.py:773`), and `_unauthorized_additions`
  (`:705-707`) exists precisely so "a candidate classification" cannot
  authorize itself — the candidate already classifies `GoalStatus` DOMAIN
  (`quality/execution-lifecycles.json:89-92`), which is why the ledger entry is
  not the defect.
- **Handoff re-demonstrated by execution this round** (round-74 simulation
  rebuilt from scratch): SIM `69e48ef4610a` = develop tree + PR #1938's grant
  (its `ratchet-authorizations.json` carries exactly one execution-lifecycles
  entry: `maistro.goals.model::GoalStatus`, owner `@BlakeMatthews-dev`, issue
  `#1572`), parented on `origin/develop`; SIM2 `44774ba56ff3` = this branch's
  tree parented on SIM; temp worktree at SIM2 with `RATCHET_BASE_REV=<SIM>`:
  gate **EXIT 0** — `authorized: maistro.goals.model::GoalStatus #1572 ...
  OK: 20 work-state vocabularies, all classified`. Control run on the same
  SIM2 worktree with `RATCHET_BASE_REV=3c761d14db94`: **EXIT 1** with the same
  sole finding (merge-base reduction to the grantless develop). Conclusion:
  once the grant lands on develop (merge grant-only PR #1938), this branch's
  gate and shipped-ledger test pass with **zero branch edits**.
- No in-branch repair exists: renaming/removing `GoalStatus` violates the
  issue-mandated lifecycle (active/satisfied/cancelled/failed/superseded) or
  dodges the work-state detector (prohibited weakening);
  `RATCHET_BASE_REV=HEAD` self-reference is refused by `_refuse_self_reference`
  (`ratchet_provenance.py:258-270`).
- Captured GitHub state (dispatch-context.json, 2026-10-12T18:00:42Z): PR
  #1938 (grant-only) **open, not merged**, head `2f5dd46969fc`; issue open;
  comments are bot markers only.

## Lane-brief vulture CI-repair exception: no target

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (exact argv,
`quality.yml:1076-1081`): **exit 0**, 1323 reviewed identities -> 1323
findings, `never_allowlist: 0`. Nothing is unbanked; there is no vulture
identity to fix or amend, so the one permitted ledger amendment has no object.

## Acceptance re-executed this round

Fresh pg18 database `r77g18` (PostgreSQL 18.6, `pgvector/pgvector:pg18`
container on 127.0.0.1:5433) created for this round.

- **Fresh install / single head:** `DATABASE_URL=...r77g18 alembic upgrade
  head` exit 0 from empty; final step `062 -> 063, The canonical Goal store`;
  `alembic current` = `063 (head)`; `alembic_version` stamp `063`; exactly 3
  `canonical_goal*` tables (`canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions`).
- **Goal acceptance (AC1-AC6):** `uv run pytest
  packages/maistro-core/tests/goals -q` with `MAISTRO_REQUIRE_PG_LEGS=1` +
  both DSNs: **70 passed / 0 failed / 0 skipped**. Criterion map (names
  confirmed in source this round): conformance round-trip `[memory, sqlite,
  postgres]` (AC1); `test_goal_revision_chain_is_append_only_with_one_cas_winner`
  (`:198`), `test_concurrent_transitions_have_exactly_one_winner` (`:279`),
  CAS + terminal-is-final legs (AC2); `test_subgoal_lineage_preserves_parent_
  goal_and_project` (`:295`) + `test_agent_reassignment_is_an_explicit_
  recorded_transition` (`:334`) (AC3); `test_run_goal_binding.py` immutable
  admission binding (AC4); `test_two_principals_cannot_reach_each_other_s_
  goals` (`:399`) with foreign==missing (`test_missing_goal_is_goal_not_found_
  on_every_read`, `:353`) (AC5); `test_goal_wiring.py` shipped-Container
  exposure (AC6); plus `test_goal_pg_schema_agreement.py` (migration DDL ==
  ensure-schema) and `test_goal_restart_readback.py` (durable restart
  readback). Note: the run-binding postgres leg requires a **migrated**
  database (`test_run_goal_binding.py:61` skip message); against the empty
  fresh DB it errors `UndefinedTableError: relation "canonical_projects"`,
  which is the documented operator artifact, green on the migrated DB.
- **Full migration battery:** `uv run pytest tests/migrations -q` with
  `MAISTRO_TEST_DATABASE_URL`/`MAISTRO_TEST_PG_DSN`/`DATABASE_URL` exported:
  **168 passed / 0 skipped / 0 failed** (chain + single head, installed-base
  forward upgrades from the actual pre-Goal develop snapshots c560d4c/4675101,
  downgrade/refusal/reapplication).
- **Convergence freeze (AC7):** `uv run python
  scripts/check-m1-convergence-freeze.py --base 3c761d14db944a727fa0744444bc67
  cfe36d49f7` (CI argv shape, `formal-conformance.yml:70-78` `args=(--base
  "$BASE_SHA")`) **exit 0**; direct `grep -rn "GoalRun|OrchestratorRun"
  packages/maistro-core/src packages/maistro-server/src packages/hive-conductor
  --include="*.py"` = no matches (grep exit 1).
- **Production composition (source-read):** `container.py:42-44` imports
  `ScopedGoalStore`/`GoalStore`/`wire_goal_store`; `:268-273` `goal_store`
  field; `:276-286` `goal_reader` property -> `ScopedGoalStore(self.goal_store,
  self.workspace_store)` over the canonical Workspace authorization seam
  (#1150); `:2412-2414` `goal_store = await wire_goal_store(db_pool,
  pg_pool=pg_pool)` inside `create_container`. Both shipped compositions build
  through the container: maistro-server `main.py:29` imports `create_container`
  (composed ~`:339-344`); hive `backend/adapters/maistro_core.py:148` imports
  and `:195` calls `container = await create_container(config)`. Not
  tests-only.
- **Driver checks at this head** (job check-*.log): sync ok, ruff check "All
  checks passed!", format "3288 files already formatted", root suite
  `161 passed, 28 skipped`, suite inventory ok (`16334` identities, 0
  duplicates).
- **mypy:** AGENTS.md argv across all seven `packages/*/src` trees —
  **Success: no issues found in 899 source files**.
- **Local-only artifact (not a branch defect), reproduced:** `tests/
  test_branch_independence_repository.py::test_every_quality_json_state_
  surface_is_classified_once` fails in this worktree only, because the
  untracked, gitignored scratch file `quality/ac-state.json` (`.gitignore:81`)
  is seen by the checker's directory scan. CI passed this test (the merge-queue
  failure was the ledger test only). The scratch file was left untouched.

## Verdict

**BLOCKED** — unchanged and external. The sole CI failure is the
execution-lifecycles floor raise for `maistro.goals.model::GoalStatus`, which
by the two-merge rule can only be authorized by a grant already landed on
develop (grant-only PR #1938, open/unmerged at head `2f5dd46969fc`;
`origin/develop` re-fetched this round is still the grantless merge-base).
Re-executed this round: with the grant present at the base revision the gate
exits 0 with zero branch edits (SIM/SIM2 simulation + control), so the
resolution is exactly one external action — merge the grant — after which the
shipped-ledger test passes with the same resolution path. The lane-brief
vulture-ledger amendment exception has no target (gate exit 0). Docs-only
round: no code, test, or ledger changes; no inventory delta.
