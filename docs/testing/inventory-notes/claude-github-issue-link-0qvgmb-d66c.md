---
inventory-delta:
  packages/maistro-core/tests: +7
---
# claude-github-issue-link-0qvgmb-d66c

Seven new tests in `packages/maistro-core/tests/graph/durable_runs/test_frontier_cycles.py`:
bounded-cycle parity coverage for the durable Graph frontier (#44, PR #519). A conditional
back edge that flips on the second visit is proven to produce distinct canonical
NodeRuns/Attempts per visit, cycle-tagged edge decisions, a linked TraversalCommit chain,
a converging fan-in join on the cycle, and loop history that survives a SQLite reopen.
The seventh pins the deliberate divergence from `GraphRun.max_cycles`: a back edge whose
guard never flips exhausts the step budget and fails closed instead of reporting the
truncated run as COMPLETED (review finding on PR #519).
No tests were removed or moved; the delta is purely additive.
