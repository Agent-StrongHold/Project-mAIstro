# #1151 repair — re-validation at the develop-tip merge (head 09caed90d)

Lane L1151, job `25c8a981…` (25c8a981d57442e78642df83ba5858a3), repair phase.
The immediately preceding repair round (job `3026fb12…`) died on a provider
timeout with **no work performed** (`result.json`: `failure_kind:
provider_error`, head unchanged at `cfb74e8da`, nothing to salvage). The
worktree therefore arrived clean at `09caed90dc0c`, the merge of develop tip
`54068f943` ([EPIC M1-C], #2159) into `auto-1151`. This round re-executed the
validation battery first-hand at that head; no deterministic driver checks were
supplied (`manifest.json` `checks: []`, no `check-*.log` files in the job
directory), so nothing below is inherited from the driver. This record is the
round's commit.

## Merge integrity (why the prior round's evidence still binds)

Develop's new commits between the previously merged tip `9a4b0c5cc` and
`54068f943` touch **zero** lane surface files (`comm -12` of the two changed-file
lists is empty; develop's delta is `packages/hive-conductor/backend/**`, three
unrelated inventory notes, and `uv.lock`). Every lane source and test file is
byte-identical to its `b8a403689` state, the head exhaustively validated in
`1151-repair-revalidation-20261018-b8a403689.md` — including the guard's
fail-before/pass-after probe and the SQLite index's fail-before `EXPLAIN QUERY
PLAN` reproduction, which are therefore not re-run here (no code path they stub
has changed). The merge was trivial for this lane; `git status` clean before and
after.

## Executed validation (all first-hand at 09caed90d)

- `uv sync --locked --extra dev`; `uv run ruff check .` — all checks passed;
  `uv run ruff format --check .` — 3310 files already formatted.
- Gates with CI's exact arguments, all exit 0:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (1322 reviewed identities → 1322 findings, no unbanked
  identity, no ledger amendment needed); `check-suite-inventory.py` (17 suites
  ok, 31676 nodes — the +3 over the prior round's 31673 arrives with the
  develop merge's own baseline update, not from this lane);
  `check-radon-baseline.py` (137/137); `check-promotion-surface.py` (ok);
  `check-test-duplicates.py` (0 groups); `check-reachability.py` (exit 0).
  The prior round's inherited `tests/` inventory drift (+1 environmental node)
  no longer reproduces.
- `uv run pytest packages/maistro-core/tests/graph/durable_runs -q` —
  684 passed, 58 skipped, 5 xfailed. The six branch-added nodes selected by
  exact ID: 1 passed + 5 `xfail(strict)` — four "superseded by develop's
  reviewed design" (quiet-period observation guard, #2144 resume-claim
  protocol) and one genuine gap
  (`test_terminal_run_mirror_repairs_a_stale_continuation_index`, def at
  `test_canonical_durable_store.py:609` — no repairer on develop; disclosed
  scoped follow-up, parent #1151 stays open, not claimed as delivered).
- `uv run pytest packages/maistro-core/tests/runs -q` — 1256 passed,
  299 skipped (PG legs skipped without a DSN; run separately below).
  Issue-baseline files (`test_crash_window_invariants.py`,
  `test_recovery_completion_budget.py`,
  `test_run_terminal_recovery_acceptance.py`, `test_chat_attempt_recovery.py`,
  `test_execution_fencing.py`) — 62 passed.
- Real PostgreSQL (lane container `auto-1151-pg`, pgvector/pg18 on
  127.0.0.1:18551, `MAISTRO_TEST_PG_DSN` set, alembic already at head `063`):
  `tests/runs/test_pg_spine_crash_windows.py` — 9/9 passed;
  `tests/graph/durable_runs/test_cross_store_crash_reconciliation.py` —
  54 passed with the PG legs included.
- `uv run mypy packages/maistro-core/src` — the same 5 environmental
  `maistro_bootstrap.*` import-not-found errors as the prior round
  (`cli/_install.py`, `cli/_builders_tui.py`; files byte-identical to develop,
  optional `bootstrap` extra not installed in this worktree venv). Not
  branch-caused; the two lane source files type-check clean within that run.

## Standing items (unchanged, re-confirmed against the tree)

1. **PR #2153 body text drift.** The body bullet claiming an idempotent
   terminal-write retry in `runs/execution.py` contradicts the tree: the file
   is byte-identical to develop (verified again at this head,
   `git diff 54068f943..HEAD -- …/runs/execution.py` empty), and develop's
   #1288 contract forbids the in-line retry. The drop is fully disclosed
   locally (`docs/testing/inventory-notes/1151-running-reconciliation.md` and
   the prior revalidation note). Correcting the PR body is a GitHub-side edit
   outside this worktree's authority (no GitHub mutations from workers); it
   remains for the integrator.
2. **Genuine xfail gap** (stale-RUNNING-continuation repair under a terminal
   canonical Run): disclosed, strict, parent #1151 open.

No code changes this round: the repair the prior verifier requested reduces to
the GitHub-side body correction plus this validation record.
