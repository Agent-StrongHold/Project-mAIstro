---
id: ADR-099
title: Builders pipeline as a DAG with gated verify-and-revise loops
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-06-12
substrate: []
implements: []
related:
  - maistro-engine#ADR-062
  - maistro-engine#ADR-032
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/builders/test_pipeline_graph.py
  - packages/maistro-core/tests/builders/test_graph_executor.py
  - packages/maistro-core/tests/builders/test_builder_pipeline.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-099: Builders pipeline as a DAG with gated verify-and-revise loops

**Status:** Proposed

## Context

The Builders subsystem ported into maistro-core is the Stronghold "Builders 2.0"
stage machine: a linear `queued → … → completed` transition table
(`builders/orchestrator.py`) plus a stateless `(worker, stage)` dispatcher
(`builders/runtime.py`). The state machine permits backward transitions, but
nothing drives them — callers must decide to loop, there is no dependency
model, and stages cannot run in parallel.

Stronghold had a second, DAG-shaped builders lineage — **Epic-15 "Builder
Pipeline as a Proper Graph"** (`PipelineNode` / `PipelineGraph` /
`GraphPipelineExecutor`, commit `e07afdc` on the `integration` branch) — that
fixed exactly these problems: explicit `depends_on` edges, `skip_if`
predicates instead of magic strings, `on_complete` hooks as data, cycle and
orphan validation before execution, and a per-node output context replacing
the single `prev_output` string. Its final story (migrate the builder
pipeline onto the graph) was never completed, and the consolidation took the
2.0 stage machine instead. The DAG lineage was orphaned.

Separately, the "loop engineering" pattern (agent runs → output graded
against verifiable criteria → revise → repeat until the criteria pass, under
explicit iteration budgets) is the missing control-flow primitive across the
engine: ADR-062's graph layer has budgets and a REVIEWER role but no
grader-gated back-edge; Epic-15 halted on first failure (its INV-07) with no
revise loop at all.

## Decision

Recreate the Epic-15 builder pipeline DAG in `maistro.builders`, faithfully,
with the improvements learned since:

1. **`builders/graph.py`** — `PipelineNode` (explicit `depends_on`, `skip_if`
   predicate, `on_complete` hook, per-node timeout) and `PipelineGraph`
   (duplicate/orphan/cycle validation via three-color DFS, ready-frontier
   resolution, `ancestors`/`descendants`). Epic-15 invariants INV-01–INV-09
   are preserved and tested.

2. **Gated verify-and-revise loops** — a node may declare a `gate`
   (verifiable acceptance predicate evaluated after completion), a
   `revise_target` (validated to be an ancestor), `max_revisions`, and a
   `gate_exhausted` policy (`fail` | `continue`). A failed gate clears the
   target and all its completed descendants, injects the gate node's output
   as `<node>_feedback` into the run context, and re-executes — bounded by
   `max_revisions` and the run's shared `IterationBudget` (reused from
   ADR-062). The dependency graph itself stays acyclic; revision is an
   executor-level re-offer, not a graph cycle.

3. **`builders/graph_executor.py`** — `GraphPipelineExecutor` drives waves of
   ready nodes **concurrently** (Epic-15 modelled parallelism but executed
   sequentially), dispatches through a `PipelineDispatcher` protocol
   (protocol-driven DI; no engine poll loop — direct await with
   `asyncio.timeout`), and halts gracefully on budget exhaustion. Failure
   semantics: no *new* node starts after a failure (INV-07 relaxed to wave
   granularity); a timed-out node never runs `on_complete` (INV-09).

4. **`builders/pipeline.py`** — the faithful five-stage default DAG
   (decompose → scaffold → implement → review → cleanup) with the original
   prompts, skip predicates, and spec-emission/property-test hooks. The
   review stage is now a gate: violations route back to implement with
   feedback (2 revisions, then `continue` so the gatekeeper cleanup stage is
   the escalation path, mirroring Stronghold's "3-pass outer loop with human
   escalation"). `RuntimeDispatcher` adapts the existing Builders 2.0
   `BuildersRuntime` so both lineages share one execution substrate.

The Builders 2.0 stage machine (`BuildersOrchestrator`) remains as the
run-level workflow record; this ADR does not remove it.

## Consequences

### Positive
- Multi-dependency stages and parallel execution of independent stages are
  now structurally possible in the builders pipeline.
- The verify-and-revise loop gives builders a first-class, budget-bounded
  "iterate until the reviewer signs off" primitive with a verifiable
  stopping condition — no caller-side loop logic.
- Graph validity (cycles, orphans, bad revise edges) fails before any agent
  runs.
- The orphaned Epic-15 design is preserved in-tree with its invariants
  encoded as tests.

### Negative / Trade-offs
- Two builder execution models coexist (stage machine + graph) until a
  follow-up decides whether `BuildersOrchestrator` becomes a thin view over
  graph runs.
- Revision clears *all* completed descendants of the revise target —
  conservative staleness, which may re-run nodes whose inputs were
  effectively unchanged.
- `maistro.builders` now imports `IterationBudget` from `maistro.graph`,
  coupling the two subsystems (acceptable: both are maistro-core, and the
  budget is the ADR-062 contract we want shared).

### Neutral
- The default pipeline names agents (quartermaster, archie, mason, auditor,
  gatekeeper) mapped onto the three `WorkerName` runtime roles; products can
  supply their own node lists and worker maps.
- A future unification with ADR-062's `maistro.graph` executor (builders
  nodes as graph roles) stays open; the dispatcher protocol is the seam.
