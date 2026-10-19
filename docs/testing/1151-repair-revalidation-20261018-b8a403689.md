# #1151 repair — re-validation and writer record (head b8a4036895497)

Lane L1151, job `f63e0ef1…` (f63e0ef1956d49359f3d28c91d9a57a2). The previous
round ended with **no commit** (provider timeout after the worker requested
deep review); the worktree arrived clean at
`b8a4036895497e8422dd2744a8ed049e521df952` with nothing to salvage, so this
round re-executed the validation first-hand at that head. Nothing below is
taken from an earlier round without being re-run, and this record is the
round's commit.

## Branch delta under validation

`origin/develop...HEAD` (merge-base `2f56be40a`) is exactly ten files: the
walker's active-Attempt guard
(`graph/durable_runs/attempt_executor.py::​_frontier_has_active_attempt`, two
call seams), the SQLite recovery ordering index
(`runs/sqlite_store.py::idx_canonical_runs_status`), four new test files, and
four inventory notes. Everything else the lane delivered (the canonical
RUNNING reconciliation sweep) is already on develop via the closed #2153.
`runs/execution.py` is byte-identical to develop — the in-line terminal-write
retry is deliberately absent per develop's #1288 contract, as disclosed in
`docs/testing/inventory-notes/1151-running-reconciliation.md`.

## Executed validation (all first-hand at this head)

- `uv run ruff check .` — all checks passed; `uv run ruff format --check .` —
  3305 files already formatted.
- `uv run mypy packages/maistro-core/src` — 5 errors, all
  `maistro_bootstrap.*` import-not-found in `cli/_install.py` /
  `cli/_builders_tui.py`, files byte-identical to develop; the optional
  `bootstrap` extra is not installed in this worktree venv
  (`import maistro_bootstrap` fails). Environmental, not introduced by the
  branch; the changed source file type-checks clean.
- Fail-before/pass-after for the guard pin, reproduced with an out-of-tree
  pytest plugin stubbing `_frontier_has_active_attempt` to `False`:
  `test_frontier_active_attempt_guard.py::test_terminal_write_failure_leaves_the_run_to_its_live_attempt`
  fails at `assert record.run.status is RunStatus.RUNNING` with
  `FAILED / 'PhysicalExecutionError: terminal completion write lost'` while
  the Attempt is still RUNNING under a live lease; with the guard intact it
  passes. Whole-suite probe with the same stub
  (`graph/durable_runs/` + `test_crash_window_invariants.py` +
  `test_recovery_completion_budget.py` + `test_chat_execution.py` +
  `test_execution_fencing.py` + `test_run_terminal_recovery_acceptance.py`):
  exactly 1 failed (the guard pin), 774 passed, 71 skipped, 5 xfailed.
- Issue baseline (memory/SQLite legs):
  `uv run --frozen pytest test_crash_window_invariants.py
  test_recovery_completion_budget.py test_run_terminal_recovery_acceptance.py
  test_cross_store_crash_reconciliation.py test_canonical_recovery_contract.py
  test_chat_attempt_recovery.py test_execution_fencing.py -q -ra`
  → 102 passed, 27 skipped (the PG legs, run separately below).
- Real PostgreSQL (lane container `auto-1151-pg` on 127.0.0.1:18551, migrated
  to alembic head `063`, `MAISTRO_TEST_PG_DSN` set): the R7 artifact
  `tests/runs/test_pg_spine_crash_windows.py` — 9 passed standalone, exact
  node IDs
  `test_a_failed_continuation_settles_its_running_run_on_the_first_tick`,
  `test_a_completed_continuation_settles_once_observed_past_the_quiet_period`,
  `test_an_elapsed_claim_under_a_running_run_is_resumed_by_the_due_tick`,
  `test_a_live_claim_is_left_to_its_walker`,
  `test_an_attempt_completion_committed_before_reconciliation_settles`,
  `test_run_settlement_lost_after_the_last_node_run_commits`,
  `test_a_frontier_node_run_without_its_checkpoint_is_made_due_and_resumed`,
  `test_the_running_sweep_pages_past_a_backlog_within_bounded_calls`,
  `test_two_replicas_sweeping_concurrently_converge_on_one_settlement`
  (actual `PgRunStore` + `PgGraphContinuationStore`, fresh recovery pool per
  fixture); with `test_cross_store_crash_reconciliation.py`: 63 passed, 0
  skipped — all 13 previously-skipped PG legs included.
- `tests/graph/durable_runs/test_canonical_durable_store.py` — 14 passed,
  5 xfailed; the six branch-added nodes selected: 1 passed + 5
  `xfail(strict=True)`, four "superseded by develop's ..." (quiet-period
  observation guard, #2144 resume-claim protocol) and one genuine gap
  (`test_terminal_run_mirror_repairs_a_stale_continuation_index`, line 600 —
  no repairer on develop; disclosed scoped follow-up, parent stays open).
  `KNOWN_GAPS = frozenset()` preserved
  (`test_crash_window_invariants.py:69`, byte-identical to develop).
- `tests/runs/test_sqlite_recovery_index.py` — 1 passed; fail-before
  reproduced out-of-tree: with the index on `(status)` alone the
  `EXPLAIN QUERY PLAN` for the sweep's page read carries
  `USE TEMP B-TREE FOR ORDER BY`; the widened
  `(status, json_extract(payload,'$.created_at'), run_id)` index drops it.
- hive-conductor baseline: `test_canonical_recovery_cadence.py` +
  `test_dag_recovery.py` — 21 passed.
- Gates with CI's exact arguments: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1322 reviewed identities
  → 1322 findings, exit 0 (no unbanked identity; no ledger amendment needed);
  `check-radon-baseline.py` — 137/137 blocks, exit 0; `check-reachability.py`
  — exit 0; `check-test-duplicates.py` — 0 byte-identical groups, exit 0;
  `check-promotion-surface.py` — ok.

## Findings for the next integration round

1. **Inherited suite-inventory drift, not branch-caused.**
   `scripts/check-suite-inventory.py` reports `DRIFT tests/: expected 5260,
   collected 5261`. The branch adds no `tests/` file and no `tests/` delta
   note; a throwaway worktree at the merge-base `2f56be40a` reproduces the
   same +1, so the drift is environmental (this venv collects one more root
   `tests/` node than CI's runner) and pre-exists the branch. The
   `packages/maistro-core/tests` suite matches its baseline+deltas
   (16443 identities). Root cause of the environment +1 not identified
   within this round's budget; recorded rather than "fixed" by editing the
   shared baseline.
2. **PR #2153 body text drift stands as previously reported** and is only
   fixable outside this worktree: the body bullet claiming an idempotent
   terminal-write retry in `runs/execution.py` contradicts the tree (file
   byte-identical to develop) and the disclosed #1288-contract drop.
3. **No develop-sync conflict exists.** The branch is behind origin/develop
   by 2 commits (`1a2e12656`, `75d2e59a2`); `comm` of changed-file lists at
   the merge-base is empty — zero file overlap — so no merge/resolution is
   required by this round.

## Acceptance mapping (scoped to this lane's delta)

- Bounded/indexed RUNNING enumeration re-deriving state from persisted facts
  → `test_the_running_sweep_pages_past_a_backlog_within_bounded_calls` (PG,
  passed) + SQLite index proof (passed, fail-before reproduced).
- QUEUED-continuation / RUNNING-Run checkpoint-1 window →
  `test_an_elapsed_claim_under_a_running_run_is_resumed_by_the_due_tick`
  (PG, passed); the no-claim immediate advance is a documented strict-xfail
  characterization (superseded by #2144's claim protocol).
- Frontier failures / persistence-failure-after-runtime → guard pin
  (fail-before/pass-after re-executed) +
  `test_a_frontier_node_run_without_its_checkpoint_is_made_due_and_resumed`
  (PG, passed).
- Idempotent, fencing-safe multi-replica recovery →
  `test_two_replicas_sweeping_concurrently_converge_on_one_settlement`
  (PG, passed).
- WAITING/PAUSED × terminal-continuation disposition rows → the strict-xfail
  characterization set; the stale-RUNNING-continuation repair remains a
  disclosed genuine gap (parent #1151 stays open), not claimed as delivered.
