---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-core/tests: +6
  packages/maistro-server/tests: +1
---

# 1169 canonical cancellation coverage

Added canonical cancellation regressions in the core Run and Runtime suites:
a provider that returns a stale success after receiving cancellation is fenced
into a cancelled Attempt, NodeRun, and Run; Runtime cancellation waits for the
child provider task; and a deadline remains a timeout when a provider swallows
cancellation. The Run suite also covers the pre-launch cancellation fence, and
the task queue now routes cancellation through the same canonical control. The
Conductor subprocess adapter kills its owned child process on cancellation rather
than abandoning it in an executor thread. Chat disconnect cleanup now uses the
same Run control, and the server API suite proves `POST /runs/{run_id}/cancel`
transitions a queued Run through the canonical service. The Conductor route
suite proves the shipped `POST /dag-runs/{run_id}/cancel` end to end on a
long-running canonical Run: a genuinely mid-flight provider is unwound, the
durable Run, NodeRun and Attempt all settle CANCELLED, the projection reads
canonical truth, and the 503 (spine unavailable) and scoped-404 refusals hold.

The Runtime cancellation boundary restructure (owner decision option a,
behavior-preserving) moves cancellation ownership from CPython's implicit
fut_waiter propagation to the explicit fence in
`PythonExecutionRuntime._run_work`: the child task is now awaited through
`asyncio.shield`, so an outer cancellation surfaces while the child is still
mid-flight and the written `work_task.cancel()` + drain block decides when
and whether the child is cancelled. Four regressions pin that contract
(+4 core node IDs): an external cancel settles the child before the
CancelledError re-raises; a provider that swallows the delivered cancellation
and returns a stale success is still fenced into a cancelled execution (the
previously unreachable arc -- under a bare await the outer cancel was
pre-cancelled into the child and could be swallowed away entirely); the
self-cancel guard returns without awaiting the active task itself; and the
deadline path still fences a mid-flight child into a RuntimeDeadlineExceeded
under the shield.
