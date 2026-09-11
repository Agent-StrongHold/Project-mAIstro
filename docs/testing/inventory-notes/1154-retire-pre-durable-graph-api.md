---
inventory-delta:
  packages/maistro-core/tests/graph: +1
---
# Issue 1154

Added `test_retired_executor.py` to pin the public-surface retirement: `maistro.graph`
and `maistro.graph.executor` no longer expose `run_graph` or `GraphRun`, and the deleted
`maistro.graph.run` module cannot be imported. Durable traversal tests remain under
`tests/graph/durable_runs/` and continue to cover Graph-domain routing and lifecycle
through canonical Run/NodeRun/Attempt evidence.
