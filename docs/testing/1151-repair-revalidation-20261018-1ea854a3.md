# #1151 repair — parked-row characterization at head 1ea854a3d

Lane L1151, job `fc389689…`, repair phase resolving the prior round's
NEEDS-REPAIR findings. Prior head `1ea854a3d` (mirror terminal spine status to
continuation) already delivered the stale-RUNNING-continuation repair the round
before had left as a strict-xfail gap. This round addressed the two remaining
findings; no production source changed.

## Findings addressed

1. **No branch repairs canonical WAITING/PAUSED x terminal COMPLETED/FAILED
   continuation.** Confirmed true of the tree — and per #1151's own dispatch
   scope that is the accepted table, not a defect to patch: repair of the four
   parked rows is DESIGN_BLOCKED ("Existing WAITING-under-COMPLETED test
   intentionally keeps WAITING with zero repair"; "Parked WAITING/PAUSED awaits
   its existing retry/answer decision; terminal history is not rewritten").
   The parent-held READY deliverable is the characterization artifact, which
   this round ships:
   `packages/maistro-core/tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py`
   (+15 nodes, note `1151-parked-terminal-continuation-disposition.md`). It
   builds all four rows as the crash residue they are, proves the sweep
   enumerates and evaluates each (visitation spy) and refuses each, pins the
   pending-decision/HITL evidence (unelapsed wait timer; durable pause entry
   with lookup projections) and the accepted-attempt NodeRun evidence, and
   proves isolation: a repairable Run (stale RUNNING continuation under a
   terminal canonical Run) settles in the same bounded tick.
2. **Coverage gap (only terminal canonical -> RUNNING continuation covered).**
   The same artifact covers the WAITING/PAUSED canonical x COMPLETED/FAILED
   continuation quadrant on memory, SQLite, and PostgreSQL continuation-store
   pairings.
3. **PR body claims an idempotent `runs/execution.py` retry the tree lacks.**
   Confirmed: the file stays byte-identical to develop
   (`git diff ce2048cd..HEAD -- packages/maistro-core/src/maistro/runs/execution.py`
   empty) and develop's #1288 contract forbids the in-line retry. The drop is
   now recorded, with the criterion mapping, in
   `docs/testing/inventory-notes/1151-running-reconciliation.md`: the
   persistence-failure acceptance is delivered through the recovery path and
   proven by `TestAPostDispatchRecordingFailureIsNeverRedispatched` (18 passed
   at this head). Correcting the PR body is a GitHub-side edit outside worker
   authority.

## Executed validation (first-hand at 1ea854a3d + this round's additions)

- `uv run ruff check .` pass; `uv run ruff format --check .` 3311 files clean.
- `check-suite-inventory.py --suite packages/maistro-core/tests` ok after the
  recorded +15; `check-test-duplicates.py` 0 groups;
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` 1322/1322 (no unbanked identity, no ledger amendment);
  `check-radon-baseline.py` 137/137; `check-promotion-surface.py` ok;
  `check-reachability.py` exit 0.
- New file: 15 passed with `MAISTRO_TEST_PG_DSN` (pgvector/pg18
  `auto-1151-pg`, 127.0.0.1:18551), 10 passed / 5 postgres legs skipped without.
- `packages/maistro-core/tests/graph/durable_runs` with DSN: 759 passed,
  4 xfailed (strict, develop-conservatism pins).
- R7 real-PG `test_pg_spine_crash_windows.py`: 11 passed; SQLite recovery-index
  and frontier-guard files pass in the same battery (83 passed / 4 xfailed
  across the five lane files).
- Issue baseline with DSN: `test_crash_window_invariants.py`,
  `test_recovery_completion_budget.py`,
  `test_run_terminal_recovery_acceptance.py`, `test_chat_attempt_recovery.py`
  (#1170 acceptance), `test_execution_fencing.py` — 62 passed, 0 skipped.
- `TestAPostDispatchRecordingFailureIsNeverRedispatched`: 18 passed.
- Hive `test_canonical_recovery_cadence.py` + `test_dag_recovery.py`: 21 passed.

## Residual (outside this lane's authority)

- PR #2153 body text drift (bullet 3 above) — integrator-side edit.
- "#804 consumes settled canonical truth" acceptance belongs to #804's lane;
  #1151 blocks it and this round adds nothing there.
- Old-reader cutover, Canvas recovery authority, and disposition of unknown
  historical data remain blocked by the reviewed contract; nothing here
  touches them.
