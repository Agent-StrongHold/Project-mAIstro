---
id: SPEC-070226-82ea
title: "Builders pipeline as DAG with gated verify-and-revise loops"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-07-02
substrate:
  - maistro-engine#ADR-062
  - maistro-engine#ADR-066
  - maistro-engine#ADR-099
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-201
implements:
  - maistro-engine#ADR-099
related:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-070
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests:
  - packages/maistro-core/tests/builders/test_dag.py
layer: Agents
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-82ea: Builders pipeline as DAG with gated verify-and-revise loops

## Context

Builders (spec → tests → code → review → retry) currently run as a flat ReAct loop. ADR-099
specifies a DAG-based orchestration where nodes are design stages (spec, test, code, review,
revise) and edges are control flow (spec complete → write tests; test pass → implement; review
pass → merge; review fail → revise). Gating rules decide when to loop back (insufficient coverage
→ revise tests; merge-conflict → retry).

## Goals

- Builders pipeline as a DAG (SPEC-201 already exists; this wires it).
- Gating rules (e.g., "if code coverage < 80%, loop back to test generation").
- Verify-and-revise loops (automated, bounded).
- Integration with graph executor (ADR-062) for orchestration.

## Non-goals

- Learning which gates work best (ADR-099 follow-up; gates are operator-tuned for Phase 1).
- AI-driven test generation (defer to Phase 2).

## Decision

Implemented in `packages/maistro-core/src/maistro/builders/dag.py`, lowering onto the
existing Epic-15 layers (`builders/graph.py` + `builders/graph_executor.py`, SPEC-201)
rather than re-implementing stage execution.

### Builders DAG structure

```python
@dataclass(frozen=True)
class StageSpec:
    name: str
    agent_name: str
    prompt_template: str
    role: AgentRole = AgentRole.CODER       # for ADR-062 conversion
    skip_if: Callable[[RunContext], bool] | None = None
    timeout_seconds: float = 600.0
    on_complete: Callable[[Any, str], Awaitable[None]] | None = None

@dataclass(frozen=True)
class BuildersDAG:
    stages: tuple[StageSpec, ...]
    edges: tuple[tuple[str, str], ...]      # forward edges only — must be acyclic
    gates: Mapping[str, Gate] = {}          # stage name → gate evaluated after it
    loop_targets: Mapping[str, str] = {}    # gated stage → ancestor to loop back to

    def validate(self) -> list[str]: ...    # names, edges, gate/loop-target pairing,
                                            # then cycles + ancestor check via lowering

def to_pipeline_graph(dag: BuildersDAG) -> PipelineGraph: ...   # SPEC-201 lowering
def builders_dag_to_graph(dag: BuildersDAG) -> GraphSpec: ...   # ADR-062 conversion
```

`default_builders_dag()` builds the SPEC's stage set with a deviation: the loop-back
edges `("review", "revise")` / `("revise", "test")` from the original sketch would make
the dependency graph cyclic, and ADR-099 requires "the dependency graph itself stays
acyclic; revision is an executor-level re-offer, not a graph cycle". So `revise` is a
*skippable ancestor* of `test` (`design → revise → test → implement → review`, skipped
on the first pass via `skip_if`, executed on every revision pass), and both gates loop
back to it via `loop_targets={"test": "revise", "review": "revise"}`.

`GraphSpec` is an alias of the canonical ADR-062 `GraphConfig` (not a new type).
Because the ADR-062 executor dispatches by `AgentRole`, stages sharing a role merge
into one node in the converted graph; gates with a `graph_condition` become
conditional loop-back edges and the iteration bound maps onto `max_cycles`.

### Verify-and-revise gates

```python
@dataclass(frozen=True)
class Gate:
    name: str
    predicate: Callable[[StageResult], bool]  # True → continue; False → loop back
    max_iterations: int = 3                   # safety valve: loop-backs permitted
    exhausted: Literal["fail", "continue"] = "fail"
    graph_condition: str | None = None        # ADR-062 edge condition equivalent
```

Deviation from the original `apply_gate` sketch: exhaustion does not silently force
forward. Per ADR-099's `gate_exhausted` policy, `"fail"` (default) fails the run
explicitly with a typed `gate_exhausted` failure; `"continue"` force-forwards (used by
the built-in review gate so a downstream cleanup/escalation stage stays reachable).
Gate enforcement lives in the SPEC-201 executor (`max_revisions`), not a standalone
`apply_gate` function. `StageResult` carries `stage`, `output`, the full run
`context`, and `iterations` (prior evaluations of the gate).

Built-in gate factories: `coverage_gate(threshold=80.0, key="coverage")` — passes when
`context[key] >= threshold`, and passes when no numeric measurement is present;
`review_gate()` — prefers an explicit boolean `context["approved"]`, else scans review
output for clean signals (APPROVED/LGTM/"no violations"/...).

### Revise stage (data, not a subclass)

Per the "agents are data" principle there is no `ReviseStage` class: revise is a
`StageSpec` whose prompt template receives `{implement}`, `{review_feedback}` and
`{test_feedback}` from the run context (the executor injects `<stage>_feedback` on
each gate failure), skipped on the first pass via `skip_if`.

### Loop termination

```python
async def run_builders_dag(
    dag: BuildersDAG,
    dispatcher: PipelineDispatcher,          # SPEC-201 DI seam — whatever runs agents
    *,
    params: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    budget: IterationBudget | None = None,   # ADR-062 shared budget
) -> BuildersDagResult: ...
```

The loop terminates when all gates pass (run completes), a gate exhausts its
`max_iterations` (policy applies), a stage fails/times out, or the shared
`IterationBudget` is spent (default `(1 + sum of gate.max_iterations) * len(stages)`
total stage executions, so a run can never hang). Deviation: instead of raising
`BuildersFailedError`, the runner never raises for run failures — it returns
`BuildersDagResult(ok, run, output, failure)` where `failure` is a typed
`BuildersDagFailure(kind, stage, detail)` with
`kind ∈ {invalid_graph, stage_failed, gate_exhausted, budget_exhausted}`.
Execution goes through the SPEC-201 `GraphPipelineExecutor` (which already owns
revision semantics); `builders_dag_to_graph` provides the ADR-062 `GraphSpec` form
for products that want to run the same pipeline as a `GraphRun`.

## Acceptance criteria

- [x] Builders DAG converts to the ADR-062 graph types (`builders_dag_to_graph` →
      `GraphConfig`); execution runs on the SPEC-201 pipeline executor sharing the
      ADR-062 `IterationBudget`.
- [x] Gates are evaluated after each stage; on failure, control loops back to correct stage.
- [x] Max iteration limit prevents infinite loops (property: iterations never exceed limit).
- [x] Coverage gate (e.g., 80%) works: if coverage < 80% after test stage, loop back; if >= 80%,
      continue to implement.
- [x] Review gate: if review is "approved", move to next; if "needs changes", loop to revise.
- [ ] Revise stage generates valid code (passes syntax check) — depends on the injected
      dispatcher/LLM; syntax-gating is a Phase 2 follow-up (non-goal: AI-driven test gen).

## Testing

- Integration: run a full Builders pipeline (design → test → implement → review → approve).
- Gate failure: design generates test that doesn't compile, gate rejects, revise fixes it.
- Loop limit: set max_iterations=2, verify loop terminates even if gate still fails.
- Property: "DAG runs to completion or hits iteration limit" (no hangs).

## References

- [ADR-099: Builders pipeline as a DAG](../adr/ADR-099-builders-pipeline-graph.md)
- [ADR-062: Graph Execution Protocol](../adr/ADR-062-graph-execution-protocol.md)
- [SPEC-201: Builders DAG runtime](SPEC-201-builders-dag-runtime.md)
- Implementation: `packages/maistro-core/src/maistro/builders/dag.py`
- Tests: `packages/maistro-core/tests/builders/test_dag.py`
