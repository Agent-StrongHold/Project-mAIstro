# Repair notes — #1572 round 83 (job 0a4805c070404f7ba08a80a4502ac3a7)

Dispatch head `c54b879b18b3affed8174d397e92639e911fa07f`, develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Round verdict: **BLOCKED on the external execution-lifecycles grant** — unchanged conclusion;
every load-bearing claim re-proven first-hand this round at the dispatch head, none assumed.
Worktree clean before this notes file; docs-only commit, no code/test/ledger changes, no
inventory delta.

## 1. External state re-check (fresh this round)

- `git fetch origin`: `origin/develop` **unchanged** at `3c761d14db94` = merge-base
  (tip == merge-base; branch 184 ahead; no develop-sync conflict exists).
- `git grep GoalStatus origin/develop -- quality/` → **exit 1, zero matches**: develop
  carries neither the GoalStatus ledger entry nor a grant.
- `git diff origin/develop HEAD -- quality/ratchet-authorizations.json` → **empty**:
  the branch carries no grant at all (in-branch grant `2f5dd4696` was removed again by
  `8510776ae` + `826cd0879` per the two-merge rule; the grant exists only in unmerged
  PR #1938).
- `git ls-remote origin refs/pull/1938/head` → still `2f5dd46969fc` (open, unmerged).
- PRIOR-RESULT DRIFT re-confirmed: prior job `2a97f5fe` (MERGE-READY, "added
  authorization for maistro.goals.model::GoalStatus") is contradicted first-hand —
  the branch has **no** authorization diff vs develop and the gate exits 1 at HEAD
  (§2).

## 2. Blocking gate at HEAD, exact CI argv

`uv run python scripts/check-execution-lifecycles.py` (quality.yml:1541, no args):

```
ratchet: execution-lifecycles  [python ast, metric v3]
  baseline: base 3c761d14db94
  candidate: c54b879b18b3
  19 classified lifecycles  ->  20 discovered lifecycles
FAIL: the execution-lifecycle ledger does not match trusted policy
  - maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted base and has no already-landed authorization
EXIT=1
```

`uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**
(`test_the_shipped_ledger_matches_the_shipped_code`, stdout gate-identical) — the
merge-queue `test: failure` is this, 1:1 (coverage `combine` inherits the failed
producer; no independent floor/diff-coverage deficit evidenced).

## 3. Two-merge mechanics re-read from source (not assumed)

- `scripts/ratchet_provenance.py:478-503` `load_authorizations` — docstring verbatim:
  "Read **from the base revision** … a new grant does not take effect in the change
  that introduces it. Authorizing a floor-raise is now two merges."
- `scripts/check-execution-lifecycles.py:773` calls it with
  `base=trusted_ref.base_sha` (the merge base), `:783` discovers at base.
- `scripts/ratchet_provenance.py:257+` `_refuse_self_reference` refuses
  `RATCHET_BASE_REV=HEAD`.
- Candidate self-classification is **present** and sound:
  `quality/execution-lifecycles.json:89` classifies `maistro.goals.model::GoalStatus`
  as DOMAIN with the intended rationale (desired-state lifecycle, deliberately not
  execution state). The defect is solely the missing *already-landed* authorization.
- No in-branch repair exists: rename/removal of GoalStatus violates the issue-mandated
  lifecycle (active/satisfied/cancelled/failed/superseded, terminal-final CAS);
  an in-branch grant is a provable no-op; `RATCHET_BASE_REV=HEAD` is refused; dodging
  the detector would be gate-weakening (prohibited). Repair = land the grant-only
  hunk on develop (merge grant-only PR #1938); then gate + test pass with zero branch
  edits (simulation proven in rounds 74/77/81).

## 4. Lane-brief vulture CI-repair exception — no amendment target

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` (quality.yml:1079-1082 exact argv) → **EXIT 0**,
`1323 reviewed identities -> 1323 findings`, `unclassified: 0`, `never_allowlist: 0`.
The CI `test: failure` is not the vulture ledger; the permitted amendment has no target.

## 5. Acceptance criteria re-executed first-hand (fresh pg18 this round)

Fresh `pgvector/pgvector:pg18` container, new DB `goals_r83` (port 15483), migrated
empty→head: `alembic upgrade head` EXIT 0, chain ends `062 -> 063, The canonical Goal
store`, `alembic heads` → `063 (head)` (single head), and `pg_tables` shows exactly
`canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions`.

`MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…`
`uv run pytest packages/maistro-core/tests/goals -q` → **70 passed / 0 failed / 0
skipped** (all three backends live). Without the env: 48 passed / 22 skipped.

Criterion → test mapping (all in the 70):

- Round-trip on all three backends via shared conformance suite →
  `test_goal_round_trips_through_the_backend` (in-memory/sqlite/pg parametrization).
- Append-only revisions, stale-refusal, exactly one CAS winner →
  `test_goal_revision_chain_is_append_only_with_one_cas_winner`,
  `test_lifecycle_transitions_cas_and_terminal_is_final`,
  `test_concurrent_transitions_have_exactly_one_winner`.
- Subgoal lineage preserves parent Goal + Project; agent change is an explicit
  recorded transition → `test_subgoal_lineage_preserves_parent_goal_and_project`,
  `test_agent_reassignment_is_an_explicit_recorded_transition`
  (`canonical_goal_transitions` table present at 063).
- Run binding at admission, immutable after; outcome never moves Goal state →
  `test_admission_binds_goal_id_and_revision`,
  `test_the_binding_is_immutable_after_admission`,
  `test_a_run_outcome_never_moves_goal_state`.
- Two principals / foreign == missing →
  `test_two_principals_cannot_reach_each_other_s_goals`,
  `test_a_foreign_goal_answers_exactly_like_a_missing_one`.
- Production composition + shipped-Container proof →
  `test_container_exposes_the_goal_store_and_its_seam`,
  `test_goal_reader_rides_the_container_end_to_end`; source read:
  `container.py:44` (import), `:273` (`goal_store` field), `:286` (`goal_reader`
  → `ScopedGoalStore`), `:2414` (`wire_goal_store` in `create_container`),
  `:2701` (passed into Container); `maistro_server/main.py:344` and
  `packages/hive-conductor/backend/adapters/maistro_core.py` both compose via
  `create_container`.
- No `GoalRun` / `OrchestratorRun` / second executor → `grep -rln
  "GoalRun\|OrchestratorRun" packages/ alembic/ scripts/` → **exit 1 (zero
  matches)**; `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7` → **EXIT 0** ("no unapproved new
  architecture island").

## 6. Driver checks this round (check-*.log) + supplemental

- sync EXIT 0, `ruff check` "All checks passed!", format 3288 files clean,
  targeted pytest 161p/28s, suite inventory `ok` (16334 identities).
- Full-repo mypy per AGENTS.md → **Success: no issues found in 899 source files**.
- Known local-only artifact, not a branch defect:
  `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
  fails here via untracked, gitignored `quality/ac-state.json` (`.gitignore:81`,
  `git status --porcelain quality/` empty); CI passed it.

## 7. Verdict

**BLOCKED** on the external maintainer execution-lifecycles grant for
`maistro.goals.model::GoalStatus` (19→20). Unblock = merge the grant-only hunk on
develop (PR #1938 split or equivalent grant-first PR); this branch then passes the
gate and the shipped-ledger test with zero further edits. Everything else about the
issue is implemented and proven at this head.
