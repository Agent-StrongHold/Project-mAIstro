# Planning-strategy benchmark: experiment record (#925, M8-D1)

Parent epic: #903 (planning, Goal decomposition, and Graph synthesis
strategies). Deliverable per the issue: a planning-strategy benchmark over a
representative Goal corpus with a GRADUATE / INCUBATE / REJECT / WATCH
disposition. **All execution remains canonical Run/NodeRun/Attempt**: the
Graph arm executes through the shipped `maistro.graph.GraphRun`/`NodeRun`
machinery; the loop arms execute through the shipped strategy classes; the
benchmark adds no scheduler, run store, or execution authority, and its
machinery lives entirely under the test tree (source-scanned).

## Hypothesis (from the issue)

Different Goal classes favor different planning/execution structures; a
single universal ReAct or DAG strategy is unlikely to dominate across
reliability, cost, and recovery.

## Canonical targets

| Arm | Production machinery driven (unmodified) |
|---|---|
| ReAct | `maistro.agents.strategies.react.ReactStrategy` — interleaved LLM/tool loop, results fed back per round |
| Explicit plan-and-execute | `maistro.agents.strategies.plan_execute.PlanExecuteStrategy` (planner) + one `ReactStrategy` executor loop per planned subtask, the strategy's own documented shape |
| Canonical Graph | `maistro.graph.run.GraphRun` planner -> coder -> reviewer — `NodeRun`s with retry classification, circuit breaker, `IterationBudget`, edge routing |

Both loop arms run standalone, which in production means every tool call is
authorized through a real `Sentinel` (`security.sentinel.policy.Sentinel`
with explicit operator grants) — the same gate standalone callers face.

## Method

`packages/maistro-core/tests/research/planning_benchmark/` (test-tree lab,
`test_benchmark_machinery_inert.py` holds the cannot-ship boundary):

- **Goal corpus** (`_world.py`): four deterministic classes —
  `single_lookup` (2-step program), `multi_step` (4), `fan_out` (5), and
  `dead_end` (a lookup whose key does not exist; a competent arm reports the
  infeasibility instead of guessing). Every Goal's program is the oracle.
- **One competent policy** (`_policy.py`): the same deterministic model
  answers for all three arms — next incomplete program step, retry an
  injected transient tool error exactly once, stop at a true dead end,
  produce the answer when the program completes. Because the policy is
  shared, any measured difference between arms is attributable to the
  structure, not the model.
- **Matched budgets** (`_harness.BenchBudget`): one budget object — 16
  model calls, 16 tool calls, 3 retries, same model name — passed to every
  arm (react round cap, plan-execute subtask cap, Graph `IterationBudget`).
- **Cost/referee separation**: costs and errors are read from the shared
  `ToolLedger` (the world's ground truth) and the policy's call counter —
  never from an arm's self-report.
- **Metrics**: goal success, tool errors, wasted tool calls (executed minus
  the Goal's minimal program), model-call and token cost, plan artifact
  (none / text / typed `PlanOutput`), verification steps, synthetic latency
  (calls x per-call constants — deterministic, never wall-clock), retries,
  and repeatability (three sweeps must be metric-identical).
- **Injections**: transient tool faults (`fail_next_lookup`) and scripted
  provider faults (`TimeoutError` on the Nth policy call — classified
  retryable by `resilience.classifier` exactly as production would).

## Results

### Clean matrix (12 cells, all successful, zero waste)

| Goal (program steps) | Arm | LLM calls | Tokens | Tool calls | Plan artifact | Verification steps | Synthetic latency |
|---|---|---|---|---|---|---|---|
| lookup-db-host (2) | react | 3 | 210 | 2 | none | 0 | 160 ms |
| lookup-db-host (2) | plan_execute | 5 | 280 | 2 | text (2) | 0 | 260 ms |
| lookup-db-host (2) | graph | 3 | 210 | 2 | structured (2) | 1 | 160 ms |
| rotate-api-key (4) | react | 5 | 350 | 4 | none | 0 | 270 ms |
| rotate-api-key (4) | plan_execute | 9 | 560 | 4 | text (4) | 0 | 470 ms |
| rotate-api-key (4) | graph | 3 | 210 | 4 | structured (4) | 1 | 170 ms |
| inventory-audit (5) | react | 6 | 420 | 5 | none | 0 | 325 ms |
| inventory-audit (5) | plan_execute | 11 | 700 | 5 | text (5) | 0 | 575 ms |
| inventory-audit (5) | graph | 3 | 210 | 5 | structured (5) | 1 | 175 ms |
| ghost-dependency (1) | react | 2 | 140 | 1 | none | 0 | 105 ms |
| ghost-dependency (1) | plan_execute | 3 | 140 | 1 | text (1) | 0 | 155 ms |
| ghost-dependency (1) | graph | 3 | 210 | 1 | structured (1) | 1 | 155 ms |

p95 synthetic latency across the matrix: **575 ms** (a deterministic function
of the cost model; identical across sweeps).

### Structural findings

1. **Cost structure differs exactly as the hypothesis predicts.** Graph pays
   a *constant* 3 model calls per Goal (role pipeline, program length
   irrelevant); ReAct pays `steps + 1`; plan-and-execute pays
   `1 + 2 x steps` (planner, then a tool turn + close turn per subtask). On
   the 5-step Goal Graph is 3x cheaper in model calls than ReAct; on the
   dead-end it is the *most* expensive arm (it still pays its verification
   step for a one-call Goal). No arm dominates across classes — the
   hypothesis is supported at the structural level.
2. **Plan inspectability is a structural property, not a model property.**
   Graph exposes a typed `PlanOutput` before/at execution; plan-and-execute
   a parseable numbered plan; ReAct ships no plan artifact at all.
3. **Verification steps exist only in the Graph arm** (reviewer node), and
   they cost the same 3 calls even where there is nothing to verify.
4. **Transient tool faults are recovered by every structure**, because the
   policy can observe the error — but at different granularity: the loop
   arms pay one extra model round (+1 call, +1 tool call); the Graph arm's
   coder retries inside its turn (+1 tool call, +0 model calls).
5. **Provider faults are recovered only by the canonical Graph arm.**
   Injected `TimeoutError` mid-loop surfaces out of `ReactStrategy.reason`
   and out of the plan-execute planner/executor calls — the strategy layer
   has no retry, and the production agent envelope (`agents/base.py`)
   catches but does not retry. The Graph arm's `NodeRun` machinery classified
   the same error as retryable TIMEOUT, re-ran the coder node, and completed
   the Goal (+1 call, `retry_count = 1`). This is the sharpest reliability
   asymmetry measured: *recovery from provider instability is a property of
   the execution structure, not of the model.*

### Mutant evidence (the benchmark can fail)

- **M-D1** (production mutation): `NodeRun._handle_attempt_exception` forced
  to never retry -> `test_provider_fault_pins_the_recovery_asymmetry` FAILS
  (graph arm no longer recovers). Restored byte-identical afterwards.
- **M-D1b** (policy mutation): planner plans half the needed subtasks ->
  `test_plan_inspectability_differs_by_structure` and four pinned-cost
  matrix cells FAIL. Restored afterwards.
- **Observed during development**: the first version of the Graph coder
  policy moved to the next program step after a transient error instead of
  retrying; the cell *passed for the wrong reason* (the deterministic
  `submit` args encode the expected answer). The shared-ledger oracle
  (`wasted_tool_calls`) is what exposed it, and the policy was fixed to
  retry inside the turn. Recorded as evidence that the referee catches
  value-blind success, and as the benchmark's known limit: with a scripted
  program, wrong-*value* pipelines are only caught through the tool ledger,
  not through answer derivation (see required evidence below).

### Fidelity caveats (recorded, not hidden)

- The `PlanExecuteStrategy` stub does not propagate provider usage (its
  `ReasoningResult` carries no token counts), so plan-execute token totals
  cover executor loops only; canonical cost for all arms is
  `llm_calls x per-call constants`. Closing the stub's usage reporting is a
  production follow-up, not benchmark scope.
- A Graph reviewer disapproval does not fail the run (`HyperagentOutput.
  success` reflects node phases, not approval) — structural observation for
  the Graph owners; the benchmark scores goal success independently.
- Latency is synthetic and structure-proportional by design: wall-clock
  p95 against deterministic machinery measures the machine, not the
  strategy. Real-latency measurement is explicitly next-evidence work.

## Disposition: INCUBATE

**Why not GRADUATE**: the issue's hypothesis concerns real models on
representative workloads (reliability, cost, real p95 latency, recovery). A
deterministic competent-policy simulation measures *structure* faithfully but
cannot measure model-dependent reliability or real latency, and no production
adoption decision should rest on it. No production change is proposed here.

**Why not REJECT / WATCH**: the structural findings are real, pinned by tests
that demonstrably fail against mutants, and the harness drives the shipped
machinery end-to-end (including real Sentinel authorization and NodeRun
retries) — the method is proven in-repo and immediately re-runnable.

**Next required evidence** (for a future GRADUATE decision):

1. Re-run the same corpus and harness with LiteLLM-backed providers (the
   harness accepts any `complete`/`llm_call` surface; only the policy fake is
   swapped for a prompted model) to measure real reliability, cost, latency
   p95, and recovery variance.
2. Extend the corpus with goals whose answers must be *derived* from tool
   outputs (value flow), so wrong-value pipelines fail the goal oracle the
   way the skipped-retry bug was caught.
3. Add the remaining M8-D arms (hierarchical decomposition, beam/MCTS plan
   search, replanning-after-observation) to the same harness, and measure
   Graph `beam_width > 1` and edge-condition replanning, which this bounded
   corpus did not exercise.
4. Route the two structural observations (plan-execute usage-reporting gap;
   reviewer disapproval not affecting run success) to the `agents` / `graph`
   owners as candidate backlog items — not via this research change.
