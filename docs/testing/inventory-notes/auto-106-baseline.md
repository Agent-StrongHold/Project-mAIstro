---
inventory-delta:
  packages/maistro-core/tests: +7
---

# M4-I adaptive-vs-fixed baseline comparison (issue #106, closing slice)

Adds the comparison epic #106's exit evidence requires: "quality-triggered
escalation and text/image selection are compared with a fixed-routing
baseline on the same workload; record task success, cost, latency and failure
cases."

- `packages/maistro-core/tests/graph/verification/test_adaptive_vs_fixed_baseline.py`
  (7 tests): one fixed workload — three easy text tasks, one hard text task
  (cheap-rung shortfall that supervision escalates), one image task (only a
  vision alias may serve it), one very-hard task (every rung misses; the
  ladder exhausts and accepts a bounded shortfall) — run under four routing
  arms through the production path: the real `llm.summarize` node, the
  governed Binding -> Invocation egress, and the durable executor's
  supervision fold, against a deterministic model-dependent stub gateway.
  Asserts the recorded comparison's structure: adaptive matches the
  strongest fixed baseline's task success at lower cost and modeled latency,
  escalated tasks pay double, supervision stays within the declared visit
  budget, and each fixed alias records the failure cases adaptivity avoids
  (shipped shortfalls; refused image tasks with no model call crossing the
  wire).
- The checked-in record generated from that harness lives in
  `docs/benchmarks/m4i-adaptive-vs-fixed-baseline.json`, regenerated with
  `uv run python scripts/bench_m4i_adaptive_vs_fixed.py --output ...`
  (`scripts/bench_m4i_adaptive_vs_fixed.py` is a thin renderer; the harness
  and its assertions stay in the test module).

Net: +7 collected node IDs on `packages/maistro-core/tests`.
