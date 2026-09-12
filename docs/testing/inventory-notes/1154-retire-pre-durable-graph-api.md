---
inventory-delta:
  packages/maistro-core/tests: -181
---
# Issue 1154

Added `test_retired_executor.py` to pin the public-surface retirement: `maistro.graph`
and `maistro.graph.executor` no longer expose `run_graph` or `GraphRun`, the retired
`NodeRun` implementation is absent from `maistro.graph.node`, and the deleted
`maistro.graph.run` module cannot be imported. Removed the direct `NodeRun.execute`
fixture; durable traversal tests remain under `tests/graph/durable_runs/` and cover
Graph-domain routing and lifecycle through canonical Run/NodeRun/Attempt evidence.
