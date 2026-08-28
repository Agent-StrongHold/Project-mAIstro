---
inventory-delta:
  packages/maistro-core/tests: +6
---
# claude-github-issue-link-0qvgmb-d66c

Six new tests in `packages/maistro-core/tests/graph/durable_runs/test_frontier_cycles.py`:
bounded-cycle parity coverage for the durable Graph frontier (#44, PR #519). A conditional
back edge that flips on the second visit is proven to produce distinct canonical
NodeRuns/Attempts per visit, cycle-tagged edge decisions, a linked TraversalCommit chain,
a converging fan-in join on the cycle, and loop history that survives a SQLite reopen.
No tests were removed or moved; the delta is purely additive.
