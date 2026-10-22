---
inventory-delta:
  packages/maistro-core/tests: +1
---
# #1151: PostgreSQL failed success-write ownership proof

Added `tests/runs/test_pg_spine_crash_windows.py::test_lost_success_write_preserves_live_ownership_then_parks`.

The existing memory-only frontier guard regression did not prove durability of
this window. The new test executes the ordinary Graph walker with `PgRunStore`
and `PgGraphContinuationStore`, then injects an ordinary `OSError` immediately
before the successful Attempt completion write. It verifies the physical node
executed once and produced output, and the completion write was not retried.

An independent PostgreSQL pool reads committed RUNNING Run/NodeRun/Attempt
state. The public `Container.recover_abandoned_attempts` tick refuses to reclaim
before the persisted lease expiry, then reclaims exactly at expiry and parks
through the existing canonical reconciler. Repeat recovery is a fixed point;
Attempt identity, ordinal and lease/fence survive; no accepted outcome or success
is fabricated. The existing recovery fixture forbids new NodeRuns, Attempts and
Invocations. No retry/disposition policy or production implementation changes.

This is **not** proof of Graph output preservation: the output was never
committed and remains absent. It is not process-kill, commit-acknowledgement-loss,
all-window coverage, or authorization for a new parked disposition. The parent
acceptance remains blocked. Execution and negative-control results are recorded
in `docs/testing/1151-repair-20261018-pg-success-write.md`.
