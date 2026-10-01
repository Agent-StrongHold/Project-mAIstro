---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-42 ambiguous effect replay guard

New composed regression test at
`packages/maistro-core/tests/graph/durable_runs/test_ambiguous_effect_replay_guard.py`.
It closes the gap between the invocation-layer unit tests
(`test_unknown_external_outcome_blocks_automatic_retry`) and the durable
executor tests (`test_unkeyed_effect_contract_overrides_a_graph_retry_budget`):
a node inside `run_durable_graph` whose external effect dies ambiguously after
dispatch (provider raises mid-flight, Invocation lands UNKNOWN) is retried by
its graph budget as three chronological NodeRuns (one Attempt each), while the
physical dispatch executes exactly once. Visits 2–3 are refused by
`InvocationExecutionService` with `UnsafeEffectRetry` because the node's
stable logical `effect_scope` makes the canonical effect contract span
NodeRun visits; the Run fails truthfully and the persisted Invocation retains
the first visit's `run_id`/`node_run_id`/`attempt_id`.

Mutation-checked: removing the stable `effect_scope` from the invoke call
(the pre-#1194 bug shape, where scope falls back to the fresh per-visit
`node_run_id`) makes the test fail with three physical dispatches, so the
guard has teeth and is not keyed on any single implementation detail.
