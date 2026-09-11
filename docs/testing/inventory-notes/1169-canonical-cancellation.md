---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-server/tests: +1
  packages/hive-conductor/backend/tests: +4
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
