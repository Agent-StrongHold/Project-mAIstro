---
inventory-delta:
  packages/maistro-canvas/tests: +17
---
# claude-ws-735-canvas-lease-followups-ab9f

The Codex review follow-ups to PR #1535 (#735) add 17 maistro-canvas node
IDs, and no existing test was removed.

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
