---
inventory-delta:
  packages/maistro-canvas/tests: +23
---
# claude-ws-735-canvas-lease-followups-ab9f

The Codex review follow-ups to PR #1535 (#735), plus the fixes for Codex's
review of this PR (#1560), add 23 maistro-canvas node IDs in total. No
pre-existing test was removed. The first round added 17; the breakdown below
is that round, and the second round is described after it.

Eight are runner lifecycle tests in `test_job_runner_lifecycle.py`:

- a stale completion after a reclaim under the same worker id
- a completion write that must not overwrite a mid-call cancellation
- a reaper write that must not overwrite a concurrent cancellation
- lease expiry surviving the real executor's sanitiser
- lease renewal that stops at `max_execution_seconds`
- a cancellation-resistant stalled call
- a non-positive `max_execution_seconds` being rejected
- an over-budget pending receipt that is never claimed and is reaped to failed

Two are admission-recovery projection tests in `test_canonical_execution.py`,
both covering an exhausted orphan that is handed to the reaper instead of
being requeued.

Two are shutdown tests in `test_canvas_runner_shutdown.py`: a task that
ignores cancellation, and a runner that crashed on its own.

Five are PostgreSQL legs in `test_store_scope_conformance.py`, running against
the real `PgCanvasStore` SQL:

- attempt-generation fencing
- the status compare-and-set
- the org-scoped fenced-write lookup
- the over-budget claim guard and its reap
- `reap_once` keeping a cancellation

Three existing tests changed only the lease-expiry message they expect, so
they add no node IDs.

The second round (Codex's review of #1560) is a net +6:

- Two first-round runner tests are replaced by one. The removed tests
  asserted that the runner cancels a stalled call, which is the behaviour
  this round removes. The replacement proves renewal stops at
  `max_execution_seconds` without cancelling the call.
- Five are canonical executor integration tests:
  - the deadline is a retryable `TIMED_OUT` Attempt, not a requested cancel
  - the deadline at the retry ceiling fails both the receipt and the Run
  - the compatibility path is bounded by the timeout
  - a stage is not started after the job deadline has passed
  - a non-positive timeout is rejected
- One is an admission-recovery test for the compare-and-set write.
- One is a PostgreSQL leg proving that a stale detached write can never
  lower `attempts`.
