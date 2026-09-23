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

## Independent verification (2ba0485048d6, develop base 8bb344e32)

Re-derived from the issue and re-executed: `tests/graph/` 1091 passed / 79 skipped
(includes `test_retired_executor.py`); `tests/testing/` + `tests/orchestrator/waves/`
+ `tests/integration/test_chat_to_graph_e2e.py` + `tests/builders/` 281 passed;
`ruff check` clean; mypy clean on `maistro.graph` + `maistro.testing`;
`check-retired-guidance.py`, `check-execution-lifecycles.py`,
`check-convergence-matrix.py`, `check-suite-inventory.py` all exit 0;
`git diff --check` clean (dag.py markers resolved). Physical Graph entries all cross
`durable_runs`: master.py creates the Run then calls `run_durable_graph`;
hive-conductor `graph_runner.execute_dag` delegates to `canonical_dag_runner`;
maistro-server touches only `graph.concurrency`. `check-vulture-baseline.py` exit 1
is pre-existing at the develop base (identical terminal state in an isolated clone
of 8bb344e32); this branch's delta is banked in the candidate ledger with owner and
issue attribution (`parallel_generations`, #1154) and the residual requires the
grants-first PR per the ratchet's two-merge rule. Stop condition respected: no
executor gained persistence; `GraphRun` is retired outright.
