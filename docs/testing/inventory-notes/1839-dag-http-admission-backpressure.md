---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---
# 1839-dag-http-admission-backpressure

Adds the parameterized
`test_dag_http_capacity_refusal_returns_429` to
`packages/hive-conductor/backend/tests/test_dags_routes.py` — four collected
node IDs (named-DAG / run-champion endpoint × principal-ceiling /
Workspace-ceiling saturation). Nothing removed or reparametrised.

The test saturates the real canonical `RunStore` the DAG HTTP routes are
refused by: with the container spine wired onto the engine (same shape as the
transport-parity suite's `canonical_run_spine`), genuinely active QUEUED root
Runs are admitted through `RunStore.create_run` up to the store's enforced
ceiling — the admin principal's ceiling (8) or the Workspace ceiling (32,
seeded across other principals so the principal ceiling is not the thing that
fires). `/run-champion` cases install a real `EvolutionService` whose
population holds a genuinely champion-eligible `PipelineGenome` (the real
`PopulationStore.get_champion` #854 eligibility contract), because missing
evolution/population/champion returns before admission and is not a
saturation test.

Each case proves, against the actual route → `graph_runner.execute_dag` →
`canonical_dag_runner` adapter:

- the saturated submission gets HTTP 429, `Retry-After: 5`, and the scoped
  detail `too many active runs for this {scope}; retry shortly` — never a 200
  receipt (the pre-fix behavior returned 200 with
  `RunConcurrencyExceeded: execution failed; see server logs`, demonstrated
  fail-first);
- the refusal leaves no new canonical Run, NodeRun, Attempt, durable graph
  continuation, or Recent Runs projection row, and dispatches no model call
  (a spying `_build_llm_call` records nothing), with every admitted Run
  keeping its identity and lifecycle state (before/after snapshots);
- once capacity is released by terminalizing the admitted work
  (QUEUED → CANCELLED through the store), the same submission is admitted
  exactly once and dispatched by the same runner under its own canonical Run
  id. The named-DAG leg completes (interactive mode); the champion leg ends
  at this sandbox's ADR-093 autonomous-isolation floor, which is the
  champion handler's existing honest contract here — the leg still proves
  admission + dispatch + a terminal state through the runner.

Only the model boundary (`graph_runner._build_llm_call`) is replaced, and only
as a recording spy; `create_run` and the runner are never replaced or
pre-checked.
