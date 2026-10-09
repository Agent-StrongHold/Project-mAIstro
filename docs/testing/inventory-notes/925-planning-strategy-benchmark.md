---
inventory-delta:
  packages/maistro-core/tests: +28
---

# #925 planning-strategy benchmark (M8-D1 prototype)

Bounded research prototype: a deterministic planning-strategy benchmark lab
comparing ReAct (`ReactStrategy`), explicit plan-and-execute
(`PlanExecuteStrategy` + one executor loop per planned subtask), and the
canonical Graph role pipeline (`GraphRun` planner -> coder -> reviewer) on the
same four-class Goal corpus, under one matched budget, with recovery,
inspectability, and repeatability cells.

New files, all under `packages/maistro-core/tests/research/planning_benchmark/`:

- `_world.py` -- the deterministic Goal corpus (single_lookup / multi_step /
  fan_out / dead_end), fact base, and the `ToolLedger` that referees every
  arm's tool cost and errors.
- `_policy.py` -- the one competent-model policy all three arms share
  (OpenAI-shaped `complete` for the strategy arms, the graph `llm_call`
  surface for `GraphRun`), with retry-once-on-transient and dead-end-stop
  rules, plus scripted provider-failure injection.
- `_harness.py` -- the three arm drivers producing `StrategyMetrics`, the
  shared `BenchBudget` (model-call/tool-call caps, retry allowance, synthetic
  latency constants), the matrix sweep, and the deterministic p95.
- `test_planning_strategy_benchmark.py` -- 26 cells: the 12-cell success
  matrix with pinned costs, cost-structure and verification findings,
  dead-end reporting, plan inspectability, tool-fault recovery (x3), the
  provider-fault recovery asymmetry, budget parity, repeatability (3
  identical sweeps), and p95 recomputation.
- `test_benchmark_machinery_inert.py` -- 2 guards: no `packages/*/src`
  module imports the lab (AST import scan), and the lab defines no
  scheduler/store-like authority (it drives shipped machinery only).

Net: +28 collected node IDs on `packages/maistro-core/tests`. Experiment
record and INCUBATE disposition:
`docs/research/925-planning-strategy-benchmark.md`.
