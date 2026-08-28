---
inventory-delta:
  packages/maistro-core/tests: +41
---
# claude-issue-338-chat-admission-compensation-9a76

Thirteen new tests in one new file,
`packages/maistro-core/tests/runs/test_chat_admission_compensation.py`. Nothing
was moved, renamed or removed, so the number is not hiding a compensating
change.

They cover the compensating terminalization #338 asks for: a failure injected
after *each* admission step (the QUEUED write and the RUNNING write), the
cancellation path that `except Exception` cannot see, idempotence under repeat
and under concurrent compensation, the sanitized cause, the two paths where
nothing should be compensated at all, and the residual case where the store
stays down and the leftover is counted rather than hidden.


## Current-state observability (#338 DoD, added after review)

A further 28 node IDs, after BlakeMatthews-dev's review established that
`stranded_chat_runs_total` does not satisfy the DoD: it is a per-process
cumulative counter of compensation failures, so it reads zero on a process that
just started against a database full of stranded rows and never falls when they
are settled.

- 7 in `tests/runs/test_chat_admission_compensation.py`
  (`TestTheRecoverableSetIsObservableRightNow`) -- a stranded Run is counted and
  aged; the published gauges return to zero once it terminalizes; a compensated
  admission leaves the recoverable set empty end to end; an uncompensated one
  stays visible; the gauges are published to the registry rather than merely
  returned; the recovery tick refreshes them; and a clock behind the Run reports
  age 0 rather than a negative.
- 21 in the new `tests/runs/test_non_terminal_run_stats_conformance.py`, driving
  the shared three-backend `spine` fixture (7 cases x memory/SQLite/PostgreSQL).
  In-memory agreement would only have proved the shape; both SQL backends take
  MIN over an ISO-8601 string inside the JSON payload, which is correct only
  because that format sorts lexically in datetime order -- worth pinning against
  a real database. Verified with the PostgreSQL leg actually running (21 passed,
  0 skipped), not skipped.

The new suite needs no CI edit: `quality.yml`'s `coverage-postgres` step lists
`packages/maistro-core/tests/runs` wholesale, so it is picked up there.
