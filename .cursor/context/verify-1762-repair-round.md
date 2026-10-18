# Verify/repair #1762 (branch auto-1762) — round: develop-sync past merge-queue head — 2026-10-18

## What this round did

No code or test changes were needed or made: the narrow repair the issue demands
(`isinstance(exc, TimeoutError)` precedence over raw `401`/`403`/`429`/`503`
substring matching in `classify_failure`) and its deterministic regression
coverage are already on the branch (see
`.cursor/context/verify-1762-31d891a56.md`). This round:

1. Resolved the previous block ("branch queued in GitHub merge queue (GH006)").
   The queue head cleared (develop moved to `eec7a587039e`); merged
   `origin/develop` into `auto-1762`. `git merge-tree` predicted 0 conflicts;
   the actual merge was clean. `packages/maistro-canvas` fix and #1762 tests are
   byte-identical on both sides (only canvas delta: frontend docker-compose.yml
   +4). `quality/` ledger rows verified row-preserving in both directions:
   `git diff --numstat origin/develop -- quality/` empty; vs pre-merge head
   only additions (17/40/7 rows in three files, 0 deletions).
2. Re-ran the full validation battery on the merged head (below).

## Acceptance evidence (all executed on the merged head)

- Fix present: `packages/maistro-canvas/src/maistro_canvas/canvas/retry_policy.py::classify_failure`
  checks `isinstance(exc, TimeoutError)` before any substring match; untyped
  keyword precedence preserved (`HTTP 401/403` -> AUTH stays permanent).
- Focused selection (suite path, `-k "TestFailureClassification or execution_deadline"`):
  29 passed (23 classification cases incl. the issue's exact repro ID
  `16e5402cfaec4030ba717ef5ce22d377`, 5 parametrized full-path deadline tests
  with controlled UUIDs carrying 401/403/429/503/402 markers, 1 ceiling test).
- Deadline full-path (`test_canonical_executor_integration.py -k execution_deadline`):
  6 passed x3 repeats (11.0s each); also 6 passed under
  `PYTHONASYNCIODEBUG=1 -W error::RuntimeWarning` — no leaked renewal task.
  Assertions observed: claim count `job.attempts == 1`, `max_attempts == 2`,
  canonical Attempt `[AttemptStatus.TIMED_OUT]`, job PENDING, `error_message
  is None`, Run not CANCELLED; second `tick_once` -> DONE with
  `[TIMED_OUT, COMPLETED]` and Run COMPLETED (same logical job/Run).
- Ceiling: job FAILED with sanitised message, Run FAILED. Genuine cancellation
  keeps separate canonical behavior: `test_canonical_execution.py` 43 passed.
- Renewal-task lifetime: production
  `runner.py::_execute_claimed_with_lease_renewal` cancels and awaits the
  heartbeat in `finally`; `test_job_runner_lifecycle.py` 24 passed. No
  claim/renewal cleanup change in this round or the fix.
- Containing suite (CI's invocation): `uv run pytest packages/maistro-canvas/tests -q`
  -> 465 passed, 75 skipped (73 need `MAISTRO_TEST_PG_DSN`, 2 need `pptx`;
  environmental, pre-existing).
- Gates: `uv run ruff check .` -> pass; `uv run ruff format --check .` -> 3323
  files formatted; `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` -> 1322
  reviewed identities == 1322 findings (nothing unbanked; no ledger amendment
  needed); `uv run python scripts/check-suite-inventory.py` -> ok: 17 suites
  match (no test delta from this round; no inventory-notes entry required).
- No assertion removal, retry blanket, skip, or gate weakening: authored delta
  this round is documentation only.

## Residual finding (pre-existing, out of #1762 scope — do not "fix" here)

`maistro.runtime` <-> `maistro.runs` circular import, order-dependent:
`import maistro.runtime` first crashes
(`ImportError: cannot import name 'ExecutionCallable' from partially initialized
module 'maistro.runtime'` via `runtime.__init__` -> `maistro.extensions` ->
`sandbox` -> `runs` -> `runs.execution` -> `runtime`); entry via
`maistro.runs` resolves cleanly. Consequence: single-module collection of
`packages/maistro-canvas/tests/test_executor.py` (alone, or as an explicit node
arg) fails before any test executes; full-directory collection (what CI runs)
and `test_canonical_executor_integration.py` standalone are unaffected.
The cycle was introduced by the M1-C canonical-spine epic's deliberate
ADR-104 wiring (`from maistro import extensions` in `runtime/__init__.py`,
"static anchor ... until the M9 graph integration"); the edge set is
byte-identical at pre-merge branch head `a4a8ea6f` and at `origin/develop`
`eec7a587039e` — it predates this round and my merge did not create it. The
prior round's focused command (test_executor.py single-module) worked only
because `maistro/extensions` did not exist yet at `31d891a56`. Fixing it means
re-ordering the deliberate anchor import — a reachability-ratchet-relevant
change owned by the spine/M9 epic, not by this CI-repair lane.
