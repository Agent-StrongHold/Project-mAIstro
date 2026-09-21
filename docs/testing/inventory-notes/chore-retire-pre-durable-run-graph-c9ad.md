---
inventory-delta:
  packages/maistro-core/tests: -4
---
# chore-retire-pre-durable-run-graph-c9ad

Retiring the pre-durable `run_graph` wrapper (#1154) removes four tests. Three
of them existed only to cover code this change deletes; the fourth was folded
into a case that survives. Nothing that was being asserted about *traversal*
stopped being asserted — the two behaviours worth keeping were re-pointed at
`GraphRun` directly, which is where they always belonged.

**Deleted with the code they covered (−3).**
`TestEnsureNodeConfigs` in `tests/graph/test_harness_node.py` drove
`maistro.graph.executor._ensure_node_configs`, the wrapper's private helper
that backfilled a `NodeConfig` per role and translated a
`parallel_generations` argument into `beam_width`. The helper had exactly one
caller — `run_graph` — so it goes with it. Its three cases (a `None` config is
a no-op, a missing role is backfilled and the beam applied to every role, and
a single generation leaves `beam_width` at 1) pinned the translation, not the
beam search. The beam search itself is still covered, below.

**Folded, not dropped (−1).**
`TestRunGraphBackwardCompat` in `tests/graph/test_protocol.py` held two cases.
`test_existing_signature` asserted only that the retired wrapper accepted its
documented arguments and returned a `HyperagentOutput` — it pinned the removed
signature and has nothing left to assert. `test_parallel_generations` asserted
something real: given three candidate plans of differing strength, the
traversal generates and scores them and the run succeeds on the best. That one
survives as `TestBeamWidth::test_a_beam_keeps_the_best_of_several_generations`,
built on `GraphRun` with `NodeConfig(beam_width=3)` stated directly instead of
inferred from a `parallel_generations` argument that no longer exists.

**Re-pointed, no count change.**
`test_run_graph_wires_executor_by_role` became
`test_a_traversal_wires_the_executor_by_role`, same assertion (a role present
in `node_executors` is driven by that executor rather than `llm_call`, proven
by an `llm_call` that raises if reached), built on `GraphRun` instead of the
wrapper.

Both surviving cases are explicitly scoped as Graph-domain traversal with no
universal lifecycle authority: they claim no canonical Run/NodeRun/Attempt
evidence, which is the distinction #1154 exists to make. Canonical execution
coverage lives in `tests/graph/durable_runs/`, and this change does not touch
it.
