# #1572 repair verification — round 71 (2026-10-12)

Dispatch head `7b5801bc764444f7b18b071eb42d1d66f82bb674`, base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Job `d563c328d6fb47328b1302180e75b006`. Every claim below was re-executed first-hand this round;
nothing is carried over from earlier rounds.

## Blocker re-proven (unchanged, external)

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv, `quality.yml:1541`) →
  **exit 1**, sole finding: `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent
  from the trusted base and has no already-landed authorization` (19 → 20).
- `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
  (:368, runs the gate's `main()`) → **1 failed, 28 passed**, captured stdout byte-equivalent to
  the gate run. This is the merge-queue `test: failure`.
- `git fetch origin` re-run: `origin/develop` tip == merge-base `3c761d14db94`, 0 behind /
  172 ahead → **nothing to merge, no sync conflict**, and the grant has not landed.
- `git grep GoalStatus origin/develop -- quality/` → no matches; the base's execution-lifecycles
  authorizations remain exactly RunStatus + DelegationStatus (#1136 precedent, two merges).
- Two-merge mechanism re-read from source: `scripts/ratchet_provenance.py`
  `load_authorizations(..., base)` docstring states verbatim that a grant "does not take effect in
  the change that introduces it … two merges — the grant, then the regression it permits".
- In-branch `quality/ratchet-authorizations.json` is byte-identical to `origin/develop`
  (`git diff origin/develop HEAD -- …` empty); neither side carries a GoalStatus grant, so an
  in-branch grant is a proven no-op (read from base revision).
- Dispatch comments rescanned (387 through 2026-10-12T13:53:08Z): no maintainer grant or
  authorization marker for GoalStatus; the only keyword hits are 2026-08/10 product clarifications.
- Candidate ledger already classifies `maistro.goals.model::GoalStatus` as DOMAIN with rationale
  (`quality/execution-lifecycles.json:89-92`) — classification is not the defect; authorization is.
- No in-branch repair exists without violating protocol or scope: in-branch grant = no-op (above);
  removing/renaming `GoalStatus` (`packages/maistro-core/src/maistro/goals/model.py:52-60`,
  ACTIVE/SATISFIED/CANCELLED/FAILED/SUPERSEDED) abandons the issue-mandated lifecycle or dodges the
  detector; dropping the ledger row fails the audit differently. Resolution is the external
  maintainer grant on develop (grant-only PR #1938 is that shape), then rebase.

## Lane-brief vulture CI-repair exception: no target

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (exact argv, `quality.yml:1079`) → **exit 0**, 1323 reviewed →
  1323 findings, `unclassified: 0`. Nothing to amend in `quality/vulture-baseline.json`.

## Acceptance criteria — all re-executed, all green

| Criterion | Evidence (this round) |
|---|---|
| Goal/GoalRevision round-trip, 3 backends | `packages/maistro-core/tests/goals/` → **70 passed, 0 failed, 0 skipped** with `MAISTRO_REQUIRE_PG_LEGS=1` (skips would fail); `test_goal_round_trips_through_the_backend` parametrized memory/SQLite/PG |
| Append-only, stale refused, CAS one winner | `test_goal_revision_chain_is_append_only_with_one_cas_winner`, `test_lifecycle_transitions_cas_and_terminal_is_final`, `test_concurrent_transitions_have_exactly_one_winner` (all ran in the 70) |
| Subgoal lineage + explicit recorded agent transition | `test_subgoal_lineage_preserves_parent_goal_and_project`, `test_agent_reassignment_is_an_explicit_recorded_transition` |
| Run binding immutable after admission | `test_admission_binds_goal_id_and_revision`, `test_the_binding_is_immutable_after_admission` (+ half-binding refused, outcome-never-moves-goal-state) |
| Two principals isolated; foreign == missing | `test_two_principals_cannot_reach_each_other_s_goals`, `test_a_foreign_goal_answers_exactly_like_a_missing_one` |
| Production composition (Hive + maistro-server) | `container.py:44/276/2414` `wire_goal_store` + `goal_reader` inside `create_container`; composed by `maistro_server/main.py:29/344` and `hive-conductor/backend/adapters/maistro_core.py:148/195`; `test_goal_wiring.py` (6 tests) proves the shipped Container exposes it |
| Restart read-back on durable composition | `test_goal_revisions_and_bound_run_provenance_survive_a_restart` (ran in the 70) |
| No second execution spine (freeze) | `PYTHONPATH=packages/maistro-core/src uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db944a727fa0744444bc67cfe36d49f7` → **exit 0** |
| Migration identity/ancestry preserved | Fresh pg18 `r71g18`: `alembic upgrade head` empty → single head **063**, chain prints `043 → 056` user-model (#1951/c560d4c) then `056 → 057` planner (#1914/4675101) … `062 → 063, The canonical Goal store`; DB stamped 063; `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions` present |
| Installed-base upgrade from real develop snapshots | `tests/migrations/test_goal_installed_base_upgrade.py` → **8 passed, 0 skipped** with `MAISTRO_TEST_DATABASE_URL` (c560d4c/4675101 present in clone; identity, provenance, PG forward-upgrade + read-back legs) |
| Fresh-install / chain / downgrade coverage | `tests/migrations/test_migration_chain.py + test_single_migration_head.py + test_status_domain_lockstep.py` → **29 passed, 0 skipped** on fresh `r71chain` (with both DSN env vars set) |
| Static quality | mypy **899 files clean**; driver logs green this round: `uv sync` (check-0), ruff check "All checks passed!" (check-1), format "3288 files already formatted" (check-2), fast suite 161 passed/28 skipped (check-3), suite inventory matches baseline 16334 (check-4) |

## Verdict

**BLOCKED** — implementation and every acceptance criterion are proven; the sole remaining CI
failure is the execution-lifecycles authorization for `maistro.goals.model::GoalStatus`, which by
the repo's own two-merge protocol (`scripts/ratchet_provenance.py:478-495`) can only be satisfied
by a maintainer grant landed on `origin/develop` first, then rebasing this branch. No in-branch
edit can satisfy it without self-authorization (prohibited) or scope/detector weakening
(prohibited). After the grant lands: gate + shipped-ledger test pass with zero edits to this
branch.

Docs-only round: no code, test, or ledger changes; no inventory delta.
