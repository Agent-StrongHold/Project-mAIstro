---
inventory-delta:
  packages/maistro-core/tests: +1
---

# 1151 — the walker's active-Attempt guard is pinned

`tests/graph/durable_runs/test_frontier_active_attempt_guard.py` pins
`attempt_executor._frontier_has_active_attempt`, the guard the lane's
`b49747211` added at the two seams where the durable Graph walker could
terminalize a Run whose frontier work a live Attempt still owns: the frontier
exception handler and the post-mirror loop check in `_walk_until_settled`.

The test forces the reachable window the guard exists for: a node whose
runtime work already ran, whose terminal Attempt write to COMPLETED then
fails with a plain `Exception` (the #1288 contract — the write is never
retried in-line; the walker survives). It asserts the walk leaves the Run
RUNNING with no fabricated `PhysicalExecutionError`, the Attempt still
RUNNING under a live lease, and that the bounded recovery tick — not the
losing walker — then reclaims the lapsed lease (`CANCELLED`) and parks the
NodeRun and Run `WAITING` for the retry policy (ADR-082526-b36a), the same
disposition the killed-walker `attempt_completion_write_lost` window
converges to.

Fail-before/pass-after (both executed on this lane at head `4e34b455e`):
with `_frontier_has_active_attempt` stubbed to `False`, the test fails at
`record.run.status is RunStatus.RUNNING` — the Run reads
`FAILED / 'PhysicalExecutionError: terminal completion write lost'` while its
Attempt is still RUNNING — and with the guard intact it passes. A
whole-suite probe with the same stub (durable_runs 741 + crash-window,
chat-execution, fencing, dag-recovery suites) shows no other test
regresses, so this node is the guard's only regression pin.
