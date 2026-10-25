---
inventory-delta:
  tests/: +28
---
# auto-914-cb52 — model-routing benchmark tests (issue #914)

Twenty-eight root-suite cases covering `scripts/bench_model_routing.py`, the
M8-B1 offline/replay evaluator that routes one shared task corpus through the
shipped `CostAwareRouter` and task-conditioned candidate policies against one
shared, policy-independent outcome table (research note:
`docs/research/914-task-conditioned-model-routing.md`, recorded numbers:
`docs/benchmarks/model-routing-baseline.json`).

The root suite is the coverage producer for `scripts/` (same arrangement as
`test_bench_working_memory.py`), so the benchmark's lines are scored by the
diff-coverage gate. The cases pin the properties that make the benchmark's
numbers trustworthy rather than just exercising the code:

- determinism: corpus, outcome table, and a full `run_benchmark` report are
  identical run-to-run, so the checked-in baseline is reproducible;
- the structural claim the research note rests on: the shipped router's
  selection is invariant to the task descriptor — if the router ever becomes
  task-conditioned, the benchmark's baseline is no longer a static-router
  baseline and must be re-read;
- the leakage audit is decidable, not vacuous: outcome-blind policies must
  produce zero violations, while the oracle — the one policy that reads the
  outcome table — must trip it (positive control);
- metric hygiene: shares, regret non-negativity, task-by-task oracle
  dominance, and the route-failure pricing (a failed route leaves a visible
  share deficit instead of silently renormalizing);
- the escalation shape of the outcome simulator (cheap tiers fine on easy
  work, cliff past their comfort zone) is pinned, since every recorded
  magnitude depends on it.

The suite caught one real modeling flaw during development: the first
tier-conditioned policy selected by tier preference alone and routed
31k-token tasks to a 16k-window model; the capacity test failed and the
policy now filters capacity from registry metadata before applying tier
preference.
