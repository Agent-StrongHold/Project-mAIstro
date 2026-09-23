---
inventory-delta:
  packages/maistro-core/tests: -239
---
# Issue 1154

Added `test_retired_executor.py` to pin the public-surface retirement: `maistro.graph`
and `maistro.graph.executor` no longer expose `run_graph` or `GraphRun`, the retired
lifecycle event factories are absent from `maistro.graph.events`, the retired `NodeRun`
implementation is absent from `maistro.graph.node`, and the deleted
`maistro.graph.run` and the unused pre-durable `maistro.graph.strategy` modules
cannot be imported. Removed the pre-durable `graph.phases` lifecycle module, the
direct `NodeRun.execute` fixture and the unused
pre-durable strategy fixtures; durable traversal tests remain
under `tests/graph/durable_runs/` and cover Graph-domain routing and lifecycle through
canonical Run/NodeRun/Attempt evidence. The chat-to-Graph integration fixture now
stops at classification/spec/spawn and explicitly does not execute physical Graph work.
The execution-lifecycle ledger no longer retains the deleted `GraphPhase`/`NodePhase`
identities, and the Vulture ledger prunes the remaining deleted node/lifecycle findings
(including the retired `testing.harness` event assertions). The same scan banked the
19 identities the retirement unmasked (former `run_graph` name matches such as
`parallel_generations` plus the pre-durable scout/strategy/backoff call surfaces that
the reachability ledger already holds for #44/#63 wiring); those bankings still need
the trusted-base grants per the ratchet's two-merge rule.
