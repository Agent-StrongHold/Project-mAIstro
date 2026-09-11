---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-server/tests: +1
  packages/hive-conductor/backend/tests: +1
---

# 1169 canonical cancellation coverage

Added canonical cancellation regressions in the core Run and Runtime suites:
a provider that returns a stale success after receiving cancellation is fenced
into a cancelled Attempt, NodeRun, and Run; Runtime cancellation waits for the
child provider task; and a deadline remains a timeout when a provider swallows
cancellation. The Conductor subprocess adapter also kills its owned child process on
cancellation rather than abandoning it in an executor thread. The server API suite also proves `POST /runs/{run_id}/cancel`
transitions a queued Run through the canonical service.
